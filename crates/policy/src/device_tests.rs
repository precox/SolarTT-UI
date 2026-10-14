use super::*;

fn request(engine: &Engine, command: Command) -> Request {
    Request {
        request_id: uuid::Uuid::new_v4().to_string(),
        expected_revision: Some(engine.revision()),
        command,
    }
}

fn policy(device_limit: Option<u16>) -> UserPolicy {
    UserPolicy {
        limit_bytes: None,
        expires_at: None,
        reset_monthly: false,
        device_limit,
    }
}

async fn fixture(limit: Option<u16>) -> (tempfile::TempDir, Arc<Engine>, String) {
    use std::os::unix::fs::PermissionsExt;
    let directory = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()
        .unwrap();
    let engine = Engine::open(&directory.path().join("policy.sqlite"), [9; 32]).unwrap();
    let user = engine
        .apply(request(
            &engine,
            Command::CreateUser {
                label: "Device limit fixture".into(),
                policy: policy(limit),
            },
        ))
        .await
        .unwrap()
        .0
        .resource_id
        .unwrap();
    (directory, engine, user)
}

async fn issue(engine: &Arc<Engine>, user: &str) -> Result<Mutation, Error> {
    engine
        .apply(request(
            engine,
            Command::CreateCredential {
                user_id: user.into(),
                label: "Phone".into(),
            },
        ))
        .await
        .map(|(mutation, _)| mutation)
}

async fn set_limit(
    engine: &Arc<Engine>,
    user: &str,
    limit: Option<u16>,
) -> Result<Mutation, Error> {
    engine
        .apply(request(
            engine,
            Command::SetPolicy {
                user_id: user.into(),
                policy: policy(limit),
            },
        ))
        .await
        .map(|(mutation, _)| mutation)
}

#[tokio::test]
async fn issuance_limit_is_not_a_tls_or_physical_device_limit() {
    let (_directory, engine, user) = fixture(Some(1)).await;
    let credential = issue(&engine, &user).await.unwrap().resource_id.unwrap();
    let (login, password, _) = engine.export_credential(&credential).unwrap();
    let identity = engine
        .authenticate(&STANDARD.encode(format!("{}:{}", login, password.as_str())))
        .unwrap();
    let sessions: Vec<_> = (0..3)
        .map(|_| engine.open_session(identity.clone()).unwrap())
        .collect();
    assert_eq!(engine.users()[0].active_sessions, 3);
    assert!(matches!(
        issue(&engine, &user).await,
        Err(Error::Invalid(_))
    ));
    assert!(sessions.iter().all(|session| !session.is_cancelled()));
    assert_eq!(engine.users()[0].credentials.len(), 1);
}

#[tokio::test]
async fn lowering_below_issued_profiles_fails_without_changing_access() {
    let (_directory, engine, user) = fixture(Some(2)).await;
    issue(&engine, &user).await.unwrap();
    let credential = issue(&engine, &user).await.unwrap().resource_id.unwrap();
    let before_revision = engine.revision();
    let before_policy = engine.users()[0].policy.clone();
    assert!(matches!(
        set_limit(&engine, &user, Some(1)).await,
        Err(Error::Invalid(_))
    ));
    assert_eq!(engine.revision(), before_revision);
    assert_eq!(engine.users()[0].policy, before_policy);
    assert!(engine.export_credential(&credential).is_ok());
    set_limit(&engine, &user, Some(2)).await.unwrap();
}

#[tokio::test]
async fn revoked_profiles_free_slots_without_a_lifetime_issuance_limit() {
    let (_directory, engine, user) = fixture(Some(1)).await;
    let mut first = None;
    for _ in 0..20 {
        let credential = issue(&engine, &user).await.unwrap().resource_id.unwrap();
        first.get_or_insert(credential.clone());
        assert_eq!(engine.users()[0].credentials.len(), 1);
        engine
            .apply(request(
                &engine,
                Command::RevokeCredential {
                    credential_id: credential,
                },
            ))
            .await
            .unwrap();
    }
    let fresh = issue(&engine, &user).await.unwrap().resource_id.unwrap();
    assert_ne!(Some(&fresh), first.as_ref());
    assert!(engine.export_credential(first.as_ref().unwrap()).is_err());
    // Recent revoked IDs remain attributable in the bounded audit log, not the live document.
    assert!(engine
        .audit(None)
        .unwrap()
        .iter()
        .any(|entry| entry.operation == "credential_change"
            && entry.credential_id.as_ref() == first.as_ref()));
    assert!(
        engine.persistent.lock().unwrap().document.users[0]
            .credentials
            .len()
            <= 16
    );
}

#[tokio::test]
async fn limit_survives_legacy_edits_restart_and_backup_restore() {
    let (directory, engine, user) = fixture(None).await;
    assert_eq!(engine.users()[0].policy.effective_device_limit(), 16);
    set_limit(&engine, &user, Some(1)).await.unwrap();
    issue(&engine, &user).await.unwrap();
    // A caller unaware of the new optional field edits traffic/expiry only.
    set_limit(&engine, &user, None).await.unwrap();
    assert_eq!(engine.users()[0].policy.device_limit, Some(1));
    engine
        .apply(request(
            &engine,
            Command::StartPeriod {
                user_id: user.clone(),
                period_id: "new-traffic-budget".into(),
            },
        ))
        .await
        .unwrap();
    assert_eq!(engine.users()[0].policy.device_limit, Some(1));
    let path = directory.path().join("policy.sqlite");
    let snapshot = directory.path().join("snapshot.sqlite");
    backup::backup_database(&path, &snapshot).unwrap();
    drop(engine);
    let reopened = Engine::open(&path, [9; 32]).unwrap();
    assert!(issue(&reopened, &user).await.is_err());
    assert_eq!(reopened.users()[0].policy.device_limit, Some(1));
    drop(reopened);
    let restored = directory.path().join("restored.sqlite");
    backup::restore_database(&snapshot, [9; 32], &restored).unwrap();
    let restored = Engine::open(&restored, [9; 32]).unwrap();
    assert_eq!(restored.users()[0].policy.device_limit, Some(1));
    assert!(issue(&restored, &user).await.is_err());
}

#[tokio::test]
async fn zero_limit_stops_issuance_and_out_of_range_limits_are_rejected() {
    let (_directory, engine, user) = fixture(Some(0)).await;
    assert!(issue(&engine, &user).await.is_err());
    let revision = engine.revision();
    assert!(set_limit(&engine, &user, Some(17)).await.is_err());
    assert_eq!(engine.revision(), revision);
    set_limit(&engine, &user, Some(1)).await.unwrap();
    issue(&engine, &user).await.unwrap();
    assert!(set_limit(&engine, &user, Some(0)).await.is_err());
}

#[tokio::test]
async fn rotating_a_revoked_profile_cannot_bypass_a_reduced_limit() {
    let (_directory, engine, user) = fixture(Some(2)).await;
    let revoked = issue(&engine, &user).await.unwrap().resource_id.unwrap();
    issue(&engine, &user).await.unwrap();
    engine
        .apply(request(
            &engine,
            Command::RevokeCredential {
                credential_id: revoked.clone(),
            },
        ))
        .await
        .unwrap();
    set_limit(&engine, &user, Some(1)).await.unwrap();
    let revision = engine.revision();
    assert!(engine
        .apply(request(
            &engine,
            Command::RotateCredential {
                credential_id: revoked.clone(),
            }
        ))
        .await
        .is_err());
    assert_eq!(engine.revision(), revision);
    assert!(engine.export_credential(&revoked).is_err());
    assert_eq!(
        engine.users()[0]
            .credentials
            .iter()
            .filter(|c| !c.revoked)
            .count(),
        1
    );
}

#[tokio::test]
async fn simultaneous_issuance_cannot_overbook_the_last_slot() {
    let (_directory, engine, user) = fixture(Some(2)).await;
    issue(&engine, &user).await.unwrap();
    let a = request(
        &engine,
        Command::CreateCredential {
            user_id: user.clone(),
            label: "A".into(),
        },
    );
    let b = request(
        &engine,
        Command::CreateCredential {
            user_id: user.clone(),
            label: "B".into(),
        },
    );
    let (a, b) = tokio::join!(engine.apply(a), engine.apply(b));
    assert_eq!(usize::from(a.is_ok()) + usize::from(b.is_ok()), 1);
    assert_eq!(
        engine.users()[0]
            .credentials
            .iter()
            .filter(|c| !c.revoked)
            .count(),
        2
    );
    assert!(issue(&engine, &user).await.is_err());
}
