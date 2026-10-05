use crate::{Document, Error, Ledger};
use fs2::FileExt;
use rusqlite::{params, Connection, OptionalExtension};
use std::{fs::File, path::Path};

pub struct Store {
    pub(crate) db: Connection,
    _lock: File,
}

impl Store {
    pub fn open(path: &Path) -> Result<Self, Error> {
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
            if version != 1 {
                return Err(Error::Invalid("Unsupported database schema"));
            }
        } else {
            let tables:u64 = db.query_row("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",[],|r|r.get(0))?;
            if tables != 0 {
                return Err(Error::Invalid("Database belongs to another application"));
            }
        }
        db.busy_timeout(std::time::Duration::from_secs(5))?;
        db.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
            CREATE TABLE IF NOT EXISTS document (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ledger (user_id TEXT NOT NULL, period_id TEXT NOT NULL,
                charged INTEGER NOT NULL CHECK(charged>=0), confirmed INTEGER NOT NULL CHECK(confirmed>=0),
                PRIMARY KEY(user_id, period_id));
            CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                revision INTEGER NOT NULL, resource_id TEXT, user_id TEXT);
            CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY, timestamp INTEGER NOT NULL,
                revision INTEGER NOT NULL, operation TEXT NOT NULL, subject TEXT);
            COMMIT;")?;
        let version: u32 = db.query_row("SELECT version FROM schema_version", [], |r| r.get(0))?;
        if version != 1 {
            return Err(Error::Invalid("Unsupported database schema"));
        }
        Ok(Self { db, _lock: lock })
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
        let mut query = self.db.prepare("SELECT seq,timestamp,revision,operation,subject FROM audit WHERE seq < ?1 ORDER BY seq DESC LIMIT 50")?;
        let rows = query.query_map([before], |r| {
            Ok(solartt_control_api::AuditEntry {
                seq: r.get(0)?,
                timestamp: r.get(1)?,
                revision: r.get(2)?,
                operation: r.get(3)?,
                subject: r.get(4)?,
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
        let tx = self.db.transaction()?;
        tx.execute(
            "INSERT INTO ledger VALUES (?1,?2,0,0) ON CONFLICT DO NOTHING",
            params![user, period],
        )?;
        tx.execute(
            "UPDATE ledger SET charged=charged+?3,confirmed=?4 WHERE user_id=?1 AND period_id=?2",
            params![user, period, n, c],
        )?;
        tx.commit()?;
        Ok(())
    }
    pub fn checkpoint(
        &mut self,
        user: &str,
        period: &str,
        charged: u64,
        confirmed: u64,
    ) -> Result<(), Error> {
        self.db.execute("INSERT INTO ledger VALUES (?1,?2,?3,?4)
            ON CONFLICT(user_id,period_id) DO UPDATE SET charged=excluded.charged,confirmed=excluded.confirmed",
            params![user,period,charged,confirmed])?;
        Ok(())
    }
    pub fn save_mutation(
        &mut self,
        document: &Document,
        id: &str,
        fingerprint: &str,
        resource: Option<&str>,
        user: Option<&str>,
        operation: &str,
    ) -> Result<(), Error> {
        let tx = self.db.transaction()?;
        tx.execute(
            "INSERT INTO document VALUES(1,?1) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            [serde_json::to_string(document)?],
        )?;
        tx.execute(
            "INSERT INTO requests VALUES(?1,?2,?3,?4,?5)",
            params![id, fingerprint, document.revision, resource, user],
        )?;
        tx.execute(
            "INSERT INTO audit(timestamp,revision,operation,subject) VALUES(?1,?2,?3,?4)",
            params![crate::now(), document.revision, operation, user],
        )?;
        tx.commit()?;
        Ok(())
    }
    pub fn previous(&self, id: &str, fingerprint: &str) -> Result<Option<crate::Mutation>, Error> {
        let value: Option<(String, u64, Option<String>, Option<String>)> = self
            .db
            .query_row(
                "SELECT fingerprint,revision,resource_id,user_id FROM requests WHERE id=?1",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )
            .optional()?;
        match value {
            Some((f, revision, resource_id, user_id)) if f == fingerprint => {
                Ok(Some(crate::Mutation {
                    revision,
                    resource_id,
                    user_id,
                    replay: true,
                }))
            }
            Some(_) => Err(Error::IdempotencyConflict),
            None => Ok(None),
        }
    }
}
