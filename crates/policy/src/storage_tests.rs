use super::*;
use std::os::unix::fs::PermissionsExt;

fn fixture(policy: RetentionPolicy) -> (tempfile::TempDir, Arc<Engine>) {
    let directory = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()
        .unwrap();
    let engine = Engine::open_with_retention(
        &directory.path().join("policy.sqlite"),
        [9; 32],
        "UTC",
        policy,
    )
    .unwrap();
    (directory, engine)
}
fn request(engine: &Engine, command: Command) -> Request {
    Request {
        request_id: format!("storage-{}", uuid::Uuid::new_v4()),
        expected_revision: Some(engine.revision()),
        command,
    }
}
async fn account(engine: &Arc<Engine>, limit: Option<u64>) -> (String, String, String) {
    let user = engine
        .apply(request(
            engine,
            Command::CreateUser {
                label: "Storage fixture".into(),
                policy: UserPolicy {
                    limit_bytes: limit,
                    expires_at: None,
                    reset_monthly: false,
                },
            },
        ))
        .await
        .unwrap()
        .0
        .resource_id
        .unwrap();
    let credential = engine
        .apply(request(
            engine,
            Command::CreateCredential {
                user_id: user.clone(),
                label: "Device".into(),
            },
        ))
        .await
        .unwrap()
        .0
        .resource_id
        .unwrap();
    let (username, password, _) = engine.export_credential(&credential).unwrap();
    let basic = STANDARD.encode(format!("{username}:{}", password.as_str()));
    (user, credential, basic)
}
fn disk_full(engine: &Engine, table: &str, operation: &str) {
    assert!(matches!(table, "audit" | "ledger"));
    assert!(matches!(operation, "INSERT" | "UPDATE"));
    let persistent = engine.persistent.lock().unwrap();
    persistent
        .store
        .db
        .execute_batch("CREATE TABLE storage_pressure(payload BLOB);")
        .unwrap();
    let pages: u64 = persistent
        .store
        .db
        .query_row("PRAGMA page_count", [], |r| r.get(0))
        .unwrap();
    persistent
        .store
        .db
        .pragma_update(None, "max_page_count", pages + 1)
        .unwrap();
    persistent
        .store
        .db
        .execute_batch(&format!(
            "CREATE TRIGGER force_full BEFORE {operation} ON {table}
        BEGIN INSERT INTO storage_pressure VALUES(zeroblob(1048576)); END;"
        ))
        .unwrap();
}
fn free_disk(engine: &Engine) {
    engine
        .persistent
        .lock()
        .unwrap()
        .store
        .db
        .execute_batch(
            "DROP TRIGGER force_full; DROP TABLE storage_pressure; PRAGMA max_page_count=16384;",
        )
        .unwrap();
}
fn is_full(error: &Error) -> bool {
    matches!(error,Error::Storage(rusqlite::Error::SqliteFailure(error,_)) if error.code==rusqlite::ErrorCode::DiskFull)
}

#[tokio::test]
async fn exports_record_trusted_actor_and_metadata_without_changing_policy_or_logging_secrets() {
    let (_directory, engine) = fixture(RetentionPolicy::default());
    let (user, credential, _) = account(&engine, None).await;
    let revision = engine.revision();
    let exported = engine
        .export_audited(
            "export-one".into(),
            credential.clone(),
            1234,
            |_, password, _| Ok(password.to_owned()),
        )
        .await
        .unwrap();
    let entries = engine.audit(None).unwrap();
    assert_eq!(entries[0].operation, "profile_export_prepared");
    assert_eq!(entries[0].subject.as_deref(), Some(user.as_str()));
    assert_eq!(entries[0].actor_uid, Some(1234));
    assert_eq!(
        entries[0].credential_id.as_deref(),
        Some(credential.as_str())
    );
    assert_eq!(entries[0].request_id.as_deref(), Some("export-one"));
    assert!(!serde_json::to_string(&entries).unwrap().contains(&exported));
    assert_eq!(engine.revision(), revision);
    assert_eq!(engine.applied_revision(), revision);
    let called = Arc::new(AtomicBool::new(false));
    let witness = called.clone();
    let denied = engine
        .export_audited(
            "export-denied".into(),
            uuid::Uuid::new_v4().to_string(),
            1235,
            move |_, _, _| {
                witness.store(true, Ordering::Release);
                Ok(())
            },
        )
        .await;
    assert!(matches!(denied, Err(Error::NotFound)));
    assert!(!called.load(Ordering::Acquire));
    let entries = engine.audit(None).unwrap();
    assert_eq!(entries[0].operation, "profile_export_denied");
    assert_eq!(entries[0].actor_uid, Some(1235));
    engine
        .apply(request(
            &engine,
            Command::RevokeCredential {
                credential_id: credential.clone(),
            },
        ))
        .await
        .unwrap();
    let denied = engine
        .export_audited(
            "revoked-export".into(),
            credential,
            1236,
            |_, _, _| -> Result<(), Error> { panic!("Revoked material reached the exporter") },
        )
        .await;
    assert!(matches!(denied, Err(Error::Denied)));
    let entry = &engine.audit(None).unwrap()[0];
    assert_eq!(entry.operation, "profile_export_denied");
    assert_eq!(entry.actor_uid, Some(1236));
    assert_eq!(entry.subject.as_deref(), Some(user.as_str()));
}

#[tokio::test]
async fn failed_audit_write_returns_no_profile_and_rolls_back_mutation_and_retention() {
    let (_directory, engine) = fixture(RetentionPolicy {
        audit_max_rows: 2,
        request_max_rows: 2,
        ..RetentionPolicy::default()
    });
    let (user, credential, basic) = account(&engine, None).await;
    let original = serde_json::to_string(&engine.audit(None).unwrap()).unwrap();
    let revision = engine.revision();
    disk_full(&engine, "audit", "INSERT");
    let result = engine
        .export_audited("full-export".into(), credential, 1234, |_, password, _| {
            Ok(password.to_owned())
        })
        .await;
    assert!(matches!(&result,Err(error) if is_full(error)));
    assert_eq!(
        serde_json::to_string(&engine.audit(None).unwrap()).unwrap(),
        original
    );
    let mutation = request(
        &engine,
        Command::BlockUser {
            user_id: user,
            blocked: true,
        },
    );
    let result = engine.apply_as(mutation.clone(), 1234).await;
    assert!(matches!(&result,Err(error) if is_full(error)));
    assert_eq!(engine.revision(), revision);
    assert!(engine.authenticate(&basic).is_some());
    assert_eq!(
        serde_json::to_string(&engine.audit(None).unwrap()).unwrap(),
        original
    );
    let info = engine.storage_info().unwrap();
    assert!(info.last_write_failed);
    assert_eq!(info.request_rows, 2);
    let floor: u64 = engine
        .persistent
        .lock()
        .unwrap()
        .store
        .db
        .query_row("SELECT request_floor FROM retention_state", [], |r| {
            r.get(0)
        })
        .unwrap();
    assert_eq!(floor, 0);
    free_disk(&engine);
    engine.apply_as(mutation, 1234).await.unwrap();
    assert!(engine.authenticate(&basic).is_none());
    assert!(!engine.storage_info().unwrap().last_write_failed);
    assert_eq!(engine.audit(None).unwrap()[0].actor_uid, Some(1234));
}

#[tokio::test]
async fn full_storage_cannot_publish_an_unpersisted_quota_grant() {
    let (_directory, engine) = fixture(RetentionPolicy::default());
    let (_, _, basic) = account(&engine, Some(10)).await;
    let session = engine
        .open_session(engine.authenticate(&basic).unwrap())
        .unwrap();
    disk_full(&engine, "ledger", "UPDATE");
    assert!(engine.reserve(&session, 1, false).await.is_err());
    let view = &engine.users()[0];
    assert_eq!(view.charged_bytes, 0);
    assert_eq!(view.available_lease_bytes, 0);
    assert_eq!(view.pending_bytes, 0);
    let ledger = engine
        .persistent
        .lock()
        .unwrap()
        .store
        .ledger(&view.id, &view.period_id)
        .unwrap();
    assert_eq!(ledger.charged, 0);
    assert!(engine.storage_info().unwrap().last_write_failed);
    free_disk(&engine);
    engine
        .reserve(&session, 10, false)
        .await
        .unwrap()
        .finish(10)
        .unwrap();
    assert_eq!(engine.users()[0].confirmed_bytes, 10);
    assert!(session.is_cancelled());
}

#[tokio::test]
async fn failed_checkpoint_and_restart_never_refund_unknown_spend() {
    let (directory, engine) = fixture(RetentionPolicy::default());
    let (_, _, basic) = account(&engine, Some(100)).await;
    let session = engine
        .open_session(engine.authenticate(&basic).unwrap())
        .unwrap();
    engine
        .reserve(&session, 100, false)
        .await
        .unwrap()
        .finish(17)
        .unwrap();
    disk_full(&engine, "ledger", "UPDATE");
    assert!(matches!(engine.checkpoint(),Err(error) if is_full(&error)));
    assert_eq!(engine.users()[0].confirmed_bytes, 17);
    // Drop without clean close. The durable lease must remain charged despite the failed checkpoint.
    drop(session);
    drop(engine);
    let restarted = Engine::open(&directory.path().join("policy.sqlite"), [9; 32]).unwrap();
    assert_eq!(restarted.users()[0].charged_bytes, 100);
    assert_eq!(restarted.users()[0].available_lease_bytes, 0);
    assert!(restarted.authenticate(&basic).is_none());
}

#[tokio::test]
async fn retention_and_period_cap_preserve_old_spend_and_expire_original_retries() {
    let (directory, engine) = fixture(RetentionPolicy {
        audit_max_rows: 3,
        request_max_rows: 2,
        periods_per_user: 2,
        ..RetentionPolicy::default()
    });
    let (user, credential, basic) = account(&engine, Some(10)).await;
    let session = engine
        .open_session(engine.authenticate(&basic).unwrap())
        .unwrap();
    engine
        .reserve(&session, 10, false)
        .await
        .unwrap()
        .finish(6)
        .unwrap();
    let period_request = request(
        &engine,
        Command::StartPeriod {
            user_id: user.clone(),
            period_id: "second".into(),
        },
    );
    engine.apply(period_request.clone()).await.unwrap();
    engine
        .reserve(&session, 10, false)
        .await
        .unwrap()
        .finish(3)
        .unwrap();
    let failed = engine
        .apply(request(
            &engine,
            Command::StartPeriod {
                user_id: user.clone(),
                period_id: "third".into(),
            },
        ))
        .await;
    assert!(matches!(failed, Err(Error::PeriodLimit)));
    assert_eq!(engine.users()[0].period_id, "second");
    assert_eq!(engine.storage_info().unwrap().ledger_rows, 2);
    engine
        .apply(request(
            &engine,
            Command::StartPeriod {
                user_id: user,
                period_id: "initial".into(),
            },
        ))
        .await
        .unwrap();
    assert_eq!(engine.users()[0].confirmed_bytes, 6);
    let permit = engine.reserve(&session, 10, false).await.unwrap();
    assert_eq!(permit.amount(), 4);
    permit.finish(4).unwrap();
    let max_seq = engine.audit(None).unwrap()[0].seq;
    engine
        .persistent
        .lock()
        .unwrap()
        .store
        .maintain(now() + 91 * 86400)
        .unwrap();
    assert!(engine.audit(None).unwrap().is_empty());
    assert_eq!(engine.storage_info().unwrap().request_rows, 0);
    assert_eq!(engine.storage_info().unwrap().ledger_rows, 2);
    assert!(matches!(
        engine.apply(period_request).await,
        Err(Error::RequestExpired)
    ));
    assert_eq!(engine.users()[0].charged_bytes, 10);
    engine
        .export_audited("new-export".into(), credential, 1234, |_, _, _| Ok(()))
        .await
        .unwrap();
    assert!(engine.audit(None).unwrap()[0].seq > max_seq);
    drop(session);
    drop(engine);
    let restarted = Engine::open_with_retention(
        &directory.path().join("policy.sqlite"),
        [9; 32],
        "UTC",
        RetentionPolicy {
            audit_max_rows: 3,
            request_max_rows: 2,
            periods_per_user: 2,
            ..RetentionPolicy::default()
        },
    )
    .unwrap();
    assert_eq!(restarted.users()[0].charged_bytes, 10);
    assert!(restarted.authenticate(&basic).is_none());
}

#[tokio::test]
async fn pinned_wal_reader_pauses_new_writes_and_allows_same_request_after_release() {
    let (directory, engine) = fixture(RetentionPolicy {
        wal_max_bytes: 4096,
        ..RetentionPolicy::default()
    });
    engine
        .persistent
        .lock()
        .unwrap()
        .store
        .db
        .busy_timeout(std::time::Duration::ZERO)
        .unwrap();
    let reader = rusqlite::Connection::open(directory.path().join("policy.sqlite")).unwrap();
    reader.execute_batch("BEGIN").unwrap();
    let _: String = reader
        .query_row("SELECT data FROM document", [], |r| r.get(0))
        .unwrap();
    let policy = UserPolicy {
        limit_bytes: None,
        expires_at: None,
        reset_monthly: false,
    };
    engine
        .apply(request(
            &engine,
            Command::CreateUser {
                label: "First".into(),
                policy: policy.clone(),
            },
        ))
        .await
        .unwrap();
    assert!(engine.storage_info().unwrap().wal_bytes >= 4096);
    let second = request(
        &engine,
        Command::CreateUser {
            label: "Second".into(),
            policy,
        },
    );
    assert!(matches!(
        engine.apply(second.clone()).await,
        Err(Error::StoragePressure)
    ));
    assert_eq!(engine.users().len(), 1);
    assert!(engine.storage_info().unwrap().last_write_failed);
    reader.execute_batch("ROLLBACK").unwrap();
    engine.apply(second).await.unwrap();
    assert_eq!(engine.users().len(), 2);
}

#[tokio::test]
async fn schema_one_upgrade_preserves_credentials_charges_and_legacy_audit_after_key_validation() {
    let (directory, engine) = fixture(RetentionPolicy::default());
    let (_, credential, basic) = account(&engine, None).await;
    let session = engine
        .open_session(engine.authenticate(&basic).unwrap())
        .unwrap();
    engine
        .reserve(&session, 32, false)
        .await
        .unwrap()
        .finish(17)
        .unwrap();
    engine.checkpoint().unwrap();
    let charged = engine.users()[0].charged_bytes;
    let revision = engine.revision();
    let (_, secret, _) = engine.export_credential(&credential).unwrap();
    drop(session);
    drop(engine);
    let path = directory.path().join("policy.sqlite");
    let db = rusqlite::Connection::open(&path).unwrap();
    drop(db);
    legacy_schema(&path);
    assert!(matches!(Engine::open(&path, [8; 32]), Err(Error::Crypto)));
    let db = rusqlite::Connection::open(&path).unwrap();
    assert_eq!(
        db.query_row("SELECT version FROM schema_version", [], |r| r
            .get::<_, u32>(0))
            .unwrap(),
        1
    );
    drop(db);
    let (checked_schema, checked_revision) =
        backup::check_database(&path, [9; 32], "UTC", RetentionPolicy::default()).unwrap();
    assert_eq!(checked_schema, 1);
    assert_eq!(checked_revision, revision);
    let db = rusqlite::Connection::open(&path).unwrap();
    assert_eq!(
        db.query_row("SELECT version FROM schema_version", [], |r| r
            .get::<_, u32>(0))
            .unwrap(),
        1
    );
    drop(db);
    let restored_path = directory.path().join("restored-v1.sqlite");
    backup::restore_database(&path, [9; 32], &restored_path).unwrap();
    let restored_engine = Engine::open(&restored_path, [9; 32]).unwrap();
    assert_eq!(restored_engine.storage_info().unwrap().schema_version, 2);
    assert_eq!(restored_engine.users()[0].charged_bytes, charged);
    drop(restored_engine);
    let upgraded = Engine::open(&path, [9; 32]).unwrap();
    assert_eq!(upgraded.revision(), revision);
    assert_eq!(upgraded.users()[0].charged_bytes, charged);
    assert_eq!(upgraded.users()[0].confirmed_bytes, 17);
    assert_eq!(upgraded.storage_info().unwrap().schema_version, 2);
    assert!(upgraded
        .audit(None)
        .unwrap()
        .iter()
        .all(|entry| entry.actor_uid.is_none()));
    let (_, restored, _) = upgraded.export_credential(&credential).unwrap();
    assert!(
        restored.as_str() == secret.as_str(),
        "Credential changed during migration"
    );
}

#[tokio::test]
async fn retained_receipt_replay_is_exact_and_aged_retry_is_rejected_before_cleanup() {
    let (_directory, engine) = fixture(RetentionPolicy {
        request_max_rows: 2,
        ..RetentionPolicy::default()
    });
    let policy = UserPolicy {
        limit_bytes: None,
        expires_at: None,
        reset_monthly: false,
    };
    let first = request(
        &engine,
        Command::CreateUser {
            label: "Replay".into(),
            policy,
        },
    );
    let original = engine.apply(first.clone()).await.unwrap().0;
    let replay = engine.apply(first.clone()).await.unwrap().0;
    assert!(replay.replay);
    assert_eq!(replay.resource_id, original.resource_id);
    assert_eq!(engine.users().len(), 1);
    let conflict = Request {
        command: Command::BlockUser {
            user_id: original.resource_id.unwrap(),
            blocked: true,
        },
        ..first.clone()
    };
    assert!(matches!(
        engine.apply(conflict).await,
        Err(Error::IdempotencyConflict)
    ));
    engine
        .persistent
        .lock()
        .unwrap()
        .store
        .db
        .execute(
            "UPDATE requests SET created_at=?1 WHERE id=?2",
            rusqlite::params![now() - 8 * 86400, first.request_id],
        )
        .unwrap();
    assert!(matches!(
        engine.apply(first).await,
        Err(Error::RequestExpired)
    ));
    assert_eq!(engine.storage_info().unwrap().request_rows, 1);
    assert_eq!(engine.users().len(), 1);
}

fn legacy_schema(path: &std::path::Path) {
    let db = rusqlite::Connection::open(path).unwrap();
    db.execute_batch(
        "BEGIN;
        DROP INDEX requests_revision; DROP INDEX requests_created;
        ALTER TABLE requests DROP COLUMN created_at;
        DROP INDEX audit_timestamp; ALTER TABLE audit RENAME TO audit_v2;
        CREATE TABLE audit (seq INTEGER PRIMARY KEY, timestamp INTEGER NOT NULL,
            revision INTEGER NOT NULL, operation TEXT NOT NULL, subject TEXT);
        INSERT INTO audit SELECT seq,timestamp,revision,operation,subject FROM audit_v2;
        DROP TABLE audit_v2; DROP TABLE retention_state;
        UPDATE schema_version SET version=1; COMMIT;",
    )
    .unwrap();
}

#[tokio::test]
async fn failed_schema_migration_rolls_back_all_ddl_and_can_retry_after_space_is_available() {
    let (directory, engine) = fixture(RetentionPolicy::default());
    let (_, credential, _) = account(&engine, None).await;
    let revision = engine.revision();
    let (_, secret, _) = engine.export_credential(&credential).unwrap();
    drop(engine);
    let path = directory.path().join("policy.sqlite");
    legacy_schema(&path);
    let db = rusqlite::Connection::open(&path).unwrap();
    db.execute_batch(
        "CREATE TABLE pressure(payload BLOB); INSERT INTO pressure VALUES(zeroblob(524288));",
    )
    .unwrap();
    let pages: u64 = db.query_row("PRAGMA page_count", [], |r| r.get(0)).unwrap();
    let page_size: u64 = db.query_row("PRAGMA page_size", [], |r| r.get(0)).unwrap();
    drop(db);
    let result = Engine::open_with_retention(
        &path,
        [9; 32],
        "UTC",
        RetentionPolicy {
            database_max_bytes: pages * page_size,
            ..RetentionPolicy::default()
        },
    );
    assert!(matches!(result,Err(error) if is_full(&error)));
    let db = rusqlite::Connection::open(&path).unwrap();
    assert_eq!(
        db.query_row("SELECT version FROM schema_version", [], |r| r
            .get::<_, u32>(0))
            .unwrap(),
        1
    );
    let created: u64 = db
        .query_row(
            "SELECT count(*) FROM pragma_table_info('requests') WHERE name='created_at'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(created, 0);
    let actor: u64 = db
        .query_row(
            "SELECT count(*) FROM pragma_table_info('audit') WHERE name='actor_uid'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(actor, 0);
    db.execute_batch("DROP TABLE pressure;").unwrap();
    drop(db);
    let repaired = Engine::open(&path, [9; 32]).unwrap();
    assert_eq!(repaired.storage_info().unwrap().schema_version, 2);
    assert_eq!(repaired.revision(), revision);
    let (_, restored, _) = repaired.export_credential(&credential).unwrap();
    assert!(
        restored.as_str() == secret.as_str(),
        "Migration retry changed the credential"
    );
}
