use crate::{retention::RetentionPolicy, Document, Error, Ledger};
use fs2::FileExt;
use rusqlite::{params, Connection, OptionalExtension};
use std::{
    fs::File,
    path::{Path, PathBuf},
};

struct Receipt {
    fingerprint: String,
    revision: u64,
    resource_id: Option<String>,
    user_id: Option<String>,
    created_at: i64,
}

pub struct Store {
    pub(crate) db: Connection,
    _lock: File,
    policy: RetentionPolicy,
    wal: PathBuf,
    last_write_failed: bool,
}

impl Store {
    pub fn open(path: &Path, policy: RetentionPolicy) -> Result<Self, Error> {
        policy.validate()?;
        use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        let parent_meta = std::fs::metadata(parent)?;
        if !parent_meta.is_dir()
            || parent_meta.uid() != unsafe { libc::geteuid() }
            || parent_meta.mode() & 0o077 != 0
        {
            return Err(Error::Invalid(
                "Database directory must be owned and private",
            ));
        }
        let mut lock_name = path.as_os_str().to_owned();
        lock_name.push(".lock");
        let lock = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(Path::new(&lock_name))?;
        let lock_meta = lock.metadata()?;
        if !lock_meta.is_file()
            || lock_meta.uid() != unsafe { libc::geteuid() }
            || lock_meta.mode() & 0o077 != 0
        {
            return Err(Error::Invalid("Unsafe database lock"));
        }
        lock.try_lock_exclusive()?;
        // Create with restricted mode BEFORE enabling WAL, whose permissions derive from the database.
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(path)?;
        let meta = file.metadata()?;
        if !meta.is_file() || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0 {
            return Err(Error::Invalid(
                "Database must be an owned private regular file",
            ));
        }
        let db = Connection::open(path)?;
        let has_schema: bool = db.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version')", [], |r|r.get(0))?;
        if has_schema {
            let version: u32 =
                db.query_row("SELECT version FROM schema_version", [], |r| r.get(0))?;
            if !matches!(version, 1 | 2) {
                return Err(Error::Invalid("Unsupported database schema"));
            }
        } else {
            let tables:u64 = db.query_row("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",[],|r|r.get(0))?;
            if tables != 0 {
                return Err(Error::Invalid("Database belongs to another application"));
            }
        }
        db.busy_timeout(std::time::Duration::from_secs(5))?;
        db.execute_batch(
            "PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA wal_autocheckpoint=256;",
        )?;
        if !has_schema {
            db.execute_batch("BEGIN IMMEDIATE;
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version VALUES(2);
                CREATE TABLE document (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                CREATE TABLE ledger (user_id TEXT NOT NULL, period_id TEXT NOT NULL,
                    charged INTEGER NOT NULL CHECK(charged>=0), confirmed INTEGER NOT NULL CHECK(confirmed>=0),
                    PRIMARY KEY(user_id, period_id));
                CREATE TABLE requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    revision INTEGER NOT NULL, resource_id TEXT, user_id TEXT, created_at INTEGER NOT NULL);
                CREATE INDEX requests_revision ON requests(revision);
                CREATE INDEX requests_created ON requests(created_at);
                CREATE TABLE audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER NOT NULL,
                    revision INTEGER NOT NULL, operation TEXT NOT NULL, subject TEXT,
                    actor_uid INTEGER, credential_id TEXT, request_id TEXT);
                CREATE INDEX audit_timestamp ON audit(timestamp);
                CREATE TABLE retention_state (id INTEGER PRIMARY KEY CHECK(id=1), request_floor INTEGER NOT NULL);
                INSERT INTO retention_state VALUES(1,0);
                COMMIT;")?;
        }
        let mut wal = path.as_os_str().to_owned();
        wal.push("-wal");
        Ok(Self {
            db,
            _lock: lock,
            policy,
            wal: wal.into(),
            last_write_failed: false,
        })
    }
    /// Called only after matching-key/timezone/credential validation by Engine.
    pub fn prepare(&mut self, document: &Document) -> Result<(), Error> {
        let page_size: u64 = self.db.query_row("PRAGMA page_size", [], |r| r.get(0))?;
        let pages = self.policy.database_max_bytes / page_size;
        let actual: u64 =
            self.db
                .query_row(&format!("PRAGMA max_page_count={pages}"), [], |r| r.get(0))?;
        if actual > pages {
            return Err(Error::Invalid("Database exceeds configured size limit"));
        }
        self.db
            .pragma_update(None, "journal_size_limit", self.policy.wal_max_bytes)?;
        let version: u32 = self
            .db
            .query_row("SELECT version FROM schema_version", [], |r| r.get(0))?;
        self.write(|db,policy| {
            let tx = db.transaction()?;
            if version == 1 {
                tx.execute_batch("ALTER TABLE requests ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0;
                    CREATE INDEX requests_revision ON requests(revision);
                    CREATE INDEX requests_created ON requests(created_at);
                    ALTER TABLE audit RENAME TO audit_v1;
                    CREATE TABLE audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER NOT NULL,
                        revision INTEGER NOT NULL, operation TEXT NOT NULL, subject TEXT,
                        actor_uid INTEGER, credential_id TEXT, request_id TEXT);
                    INSERT INTO audit(seq,timestamp,revision,operation,subject)
                        SELECT seq,timestamp,revision,operation,subject FROM audit_v1 ORDER BY seq;
                    DROP TABLE audit_v1;
                    CREATE INDEX audit_timestamp ON audit(timestamp);
                    CREATE TABLE retention_state (id INTEGER PRIMARY KEY CHECK(id=1), request_floor INTEGER NOT NULL);
                    INSERT INTO retention_state VALUES(1,0);
                    UPDATE schema_version SET version=2;")?;
                tx.execute("UPDATE requests SET created_at=coalesce((SELECT min(timestamp) FROM audit WHERE audit.revision=requests.revision),?1)",[crate::now()])?;
            }
            for user in &document.users { Self::ensure_period(&tx,policy,&user.id,&user.period_id)?; }
            Self::prune(&tx,policy,crate::now(),false,false)?;
            tx.commit()?;
            Ok(())
        })?;
        Ok(())
    }
    fn wal_bytes(&self) -> Result<u64, Error> {
        match std::fs::metadata(&self.wal) {
            Ok(metadata) => Ok(metadata.len()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(0),
            Err(e) => Err(e.into()),
        }
    }
    fn prepare_write(&self) -> Result<(), Error> {
        if self.wal_bytes()? >= self.policy.wal_max_bytes {
            let _: (i64, i64, i64) =
                self.db
                    .query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |r| {
                        Ok((r.get(0)?, r.get(1)?, r.get(2)?))
                    })?;
            if self.wal_bytes()? >= self.policy.wal_max_bytes {
                return Err(Error::StoragePressure);
            }
        }
        Ok(())
    }
    fn write<T>(
        &mut self,
        work: impl FnOnce(&mut Connection, &RetentionPolicy) -> Result<T, Error>,
    ) -> Result<T, Error> {
        let result = self
            .prepare_write()
            .and_then(|_| work(&mut self.db, &self.policy));
        self.last_write_failed = result.is_err();
        result
    }
    fn prune(
        tx: &rusqlite::Transaction<'_>,
        policy: &RetentionPolicy,
        timestamp: i64,
        audit_slot: bool,
        request_slot: bool,
    ) -> Result<(), Error> {
        let request_keep = policy.request_max_rows - u32::from(request_slot);
        let cutoff = timestamp.saturating_sub(i64::from(policy.request_max_days) * 86400);
        let deleted: Option<u64> = tx.query_row("SELECT max(revision) FROM requests WHERE created_at < ?1 OR revision NOT IN (SELECT revision FROM requests ORDER BY revision DESC LIMIT ?2)", params![cutoff,request_keep], |r|r.get(0))?;
        if let Some(revision) = deleted {
            tx.execute(
                "UPDATE retention_state SET request_floor=max(request_floor,?1) WHERE id=1",
                [revision],
            )?;
            tx.execute("DELETE FROM requests WHERE created_at < ?1 OR revision NOT IN (SELECT revision FROM requests ORDER BY revision DESC LIMIT ?2)",params![cutoff,request_keep])?;
        }
        let audit_keep = policy.audit_max_rows - u32::from(audit_slot);
        tx.execute("DELETE FROM audit WHERE timestamp < ?1 OR seq NOT IN (SELECT seq FROM audit ORDER BY seq DESC LIMIT ?2)",params![timestamp.saturating_sub(i64::from(policy.audit_max_days)*86400),audit_keep])?;
        Ok(())
    }
    pub fn maintain(&mut self, timestamp: i64) -> Result<(), Error> {
        self.write(|db, policy| {
            let tx = db.transaction()?;
            Self::prune(&tx, policy, timestamp, false, false)?;
            tx.commit()?;
            Ok(())
        })?;
        let _: (i64, i64, i64) = self
            .db
            .query_row("PRAGMA wal_checkpoint(PASSIVE)", [], |r| {
                Ok((r.get(0)?, r.get(1)?, r.get(2)?))
            })?;
        Ok(())
    }
    pub fn storage_info(&self) -> Result<solartt_control_api::StorageInfo, Error> {
        let count = |name: &str| -> Result<u64, rusqlite::Error> {
            self.db
                .query_row(&format!("SELECT count(*) FROM {name}"), [], |r| r.get(0))
        };
        let pages: u64 = self.db.query_row("PRAGMA page_count", [], |r| r.get(0))?;
        let page_size: u64 = self.db.query_row("PRAGMA page_size", [], |r| r.get(0))?;
        Ok(solartt_control_api::StorageInfo {
            schema_version: 2,
            audit_rows: count("audit")?,
            request_rows: count("requests")?,
            ledger_rows: count("ledger")?,
            audit_max_rows: self.policy.audit_max_rows,
            audit_max_days: self.policy.audit_max_days,
            request_max_rows: self.policy.request_max_rows,
            request_max_days: self.policy.request_max_days,
            periods_per_user: self.policy.periods_per_user,
            database_bytes: pages * page_size,
            database_max_bytes: self.policy.database_max_bytes,
            wal_bytes: self.wal_bytes()?,
            wal_max_bytes: self.policy.wal_max_bytes,
            last_write_failed: self.last_write_failed,
        })
    }
    fn ensure_period(
        db: &Connection,
        policy: &RetentionPolicy,
        user: &str,
        period: &str,
    ) -> Result<(), Error> {
        let exists: bool = db.query_row(
            "SELECT EXISTS(SELECT 1 FROM ledger WHERE user_id=?1 AND period_id=?2)",
            params![user, period],
            |r| r.get(0),
        )?;
        if !exists {
            let count: u32 = db.query_row(
                "SELECT count(*) FROM ledger WHERE user_id=?1",
                [user],
                |r| r.get(0),
            )?;
            if count >= policy.periods_per_user {
                return Err(Error::PeriodLimit);
            }
            db.execute(
                "INSERT INTO ledger VALUES(?1,?2,0,0)",
                params![user, period],
            )?;
        }
        Ok(())
    }
    pub fn request_expired(&self, revision: Option<u64>) -> Result<bool, Error> {
        let floor: u64 = self.db.query_row(
            "SELECT request_floor FROM retention_state WHERE id=1",
            [],
            |r| r.get(0),
        )?;
        Ok(revision.is_some_and(|revision| revision < floor))
    }
    pub fn has_document(&self) -> Result<bool, Error> {
        Ok(self.db.query_row(
            "SELECT EXISTS(SELECT 1 FROM document WHERE id=1)",
            [],
            |r| r.get(0),
        )?)
    }
    pub fn initialize(&mut self, document: &Document) -> Result<(), Error> {
        self.db.execute(
            "INSERT INTO document VALUES(1,?1)",
            [serde_json::to_string(document)?],
        )?;
        Ok(())
    }
    pub fn audit(
        &self,
        before: Option<u64>,
    ) -> Result<Vec<solartt_control_api::AuditEntry>, Error> {
        let before = before.unwrap_or(i64::MAX as u64).min(i64::MAX as u64);
        let mut query = self.db.prepare("SELECT seq,timestamp,revision,operation,subject,actor_uid,credential_id,request_id FROM audit WHERE seq < ?1 ORDER BY seq DESC LIMIT 50")?;
        let rows = query.query_map([before], |r| {
            Ok(solartt_control_api::AuditEntry {
                seq: r.get(0)?,
                timestamp: r.get(1)?,
                revision: r.get(2)?,
                operation: r.get(3)?,
                subject: r.get(4)?,
                actor_uid: r.get(5)?,
                credential_id: r.get(6)?,
                request_id: r.get(7)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }
    pub fn load(&self) -> Result<Document, Error> {
        let text: Option<String> = self
            .db
            .query_row("SELECT data FROM document WHERE id=1", [], |r| r.get(0))
            .optional()?;
        match text {
            Some(s) => Ok(serde_json::from_str(&s)?),
            None => Ok(Document::default()),
        }
    }
    pub fn ledger(&self, user: &str, period: &str) -> Result<Ledger, Error> {
        Ok(self
            .db
            .query_row(
                "SELECT charged, confirmed FROM ledger WHERE user_id=?1 AND period_id=?2",
                params![user, period],
                |r| {
                    Ok(Ledger {
                        charged: r.get(0)?,
                        confirmed: r.get(1)?,
                    })
                },
            )
            .optional()?
            .unwrap_or_default())
    }
    pub fn grant(
        &mut self,
        user: &str,
        period: &str,
        amount: u64,
        confirmed: u64,
    ) -> Result<(), Error> {
        let n = i64::try_from(amount).map_err(|_| Error::Invalid("Quota is too large"))?;
        let c = i64::try_from(confirmed).map_err(|_| Error::Invalid("Counter overflow"))?;
        self.write(|db,policy| {
            let tx = db.transaction()?;
            Self::ensure_period(&tx,policy,user,period)?;
            tx.execute("UPDATE ledger SET charged=charged+?3,confirmed=?4 WHERE user_id=?1 AND period_id=?2",params![user,period,n,c])?;
            tx.commit()?;
            Ok(())
        })
    }
    pub fn checkpoint(
        &mut self,
        user: &str,
        period: &str,
        charged: u64,
        confirmed: u64,
    ) -> Result<(), Error> {
        self.write(|db, policy| {
            let tx = db.transaction()?;
            Self::ensure_period(&tx, policy, user, period)?;
            tx.execute(
                "UPDATE ledger SET charged=?3,confirmed=?4 WHERE user_id=?1 AND period_id=?2",
                params![user, period, charged, confirmed],
            )?;
            tx.commit()?;
            Ok(())
        })
    }
    pub fn save_mutation(
        &mut self,
        document: &Document,
        fingerprint: &str,
        resource: Option<&str>,
        user: Option<&str>,
        operation: &str,
        audit: AuditContext<'_>,
    ) -> Result<(), Error> {
        self.write(|db,policy| {
            let tx = db.transaction()?;
            Self::prune(&tx,policy,crate::now(),true,true)?;
            for user in &document.users { Self::ensure_period(&tx,policy,&user.id,&user.period_id)?; }
            tx.execute("INSERT INTO document VALUES(1,?1) ON CONFLICT(id) DO UPDATE SET data=excluded.data",[serde_json::to_string(document)?])?;
            tx.execute("INSERT INTO requests VALUES(?1,?2,?3,?4,?5,?6)",params![audit.request_id,fingerprint,document.revision,resource,user,crate::now()])?;
            tx.execute("INSERT INTO audit(timestamp,revision,operation,subject,actor_uid,credential_id,request_id) VALUES(?1,?2,?3,?4,?5,?6,?7)",params![crate::now(),document.revision,operation,user,audit.actor_uid,audit.credential_id,audit.request_id])?;
            tx.commit()?;
            Ok(())
        })
    }
    pub fn record_export(
        &mut self,
        revision: u64,
        user: Option<&str>,
        operation: &str,
        audit: AuditContext<'_>,
    ) -> Result<(), Error> {
        self.write(|db,policy| {
            let tx = db.transaction()?;
            Self::prune(&tx,policy,crate::now(),true,false)?;
            tx.execute("INSERT INTO audit(timestamp,revision,operation,subject,actor_uid,credential_id,request_id) VALUES(?1,?2,?3,?4,?5,?6,?7)",params![crate::now(),revision,operation,user,audit.actor_uid,audit.credential_id,audit.request_id])?;
            tx.commit()?;
            Ok(())
        })
    }
    pub fn previous(&self, id: &str, fingerprint: &str) -> Result<Option<crate::Mutation>, Error> {
        let value: Option<Receipt> = self
            .db
            .query_row(
                "SELECT fingerprint,revision,resource_id,user_id,created_at FROM requests WHERE id=?1",
                [id],
                |r|Ok(Receipt {fingerprint:r.get(0)?,revision:r.get(1)?,resource_id:r.get(2)?,user_id:r.get(3)?,created_at:r.get(4)?}),
            )
            .optional()?;
        match value {
            Some(receipt)
                if receipt.created_at
                    < crate::now()
                        .saturating_sub(i64::from(self.policy.request_max_days) * 86400) =>
            {
                Err(Error::RequestExpired)
            }
            Some(receipt) if receipt.fingerprint == fingerprint => Ok(Some(crate::Mutation {
                revision: receipt.revision,
                resource_id: receipt.resource_id,
                user_id: receipt.user_id,
                replay: true,
            })),
            Some(_) => Err(Error::IdempotencyConflict),
            None => Ok(None),
        }
    }
}

#[derive(Clone, Copy)]
pub(crate) struct AuditContext<'a> {
    pub request_id: &'a str,
    pub actor_uid: Option<u32>,
    pub credential_id: Option<&'a str>,
}
