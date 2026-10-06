//! Host administrator utilities. Backups contain encrypted credentials and remain private.
use crate::{Engine, Error, RetentionPolicy};
use rusqlite::{Connection, DatabaseName, OpenFlags};
use std::{fs::File, path::Path};

fn private_parent(path: &Path) -> Result<(), Error> {
    use std::os::unix::fs::MetadataExt;
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let meta = std::fs::metadata(parent)?;
    if !meta.is_dir() || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0 {
        return Err(Error::Invalid("Backup directory must be owned and private"));
    }
    Ok(())
}
fn source(path: &Path) -> Result<Connection, Error> {
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    private_parent(path)?;
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0 {
        return Err(Error::Invalid(
            "Backup source must be an owned private regular file",
        ));
    }
    let db = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    let version: u32 = db.query_row("SELECT version FROM schema_version", [], |r| r.get(0))?;
    if !matches!(version, 1 | 2) {
        return Err(Error::Invalid("Unsupported database schema"));
    }
    let check: String = db.query_row("PRAGMA integrity_check", [], |r| r.get(0))?;
    if check != "ok" {
        return Err(Error::Invalid("Database integrity check failed"));
    }
    let document: String =
        db.query_row("SELECT data FROM document WHERE id=1", [], |r| r.get(0))?;
    let _: crate::Document = serde_json::from_str(&document)?;
    Ok(db)
}
/// A consistent SQLite snapshot includes WAL transactions. Never copy just the
/// live .sqlite file. This operation can run beside an active agent.
pub fn backup_database(database: &Path, destination: &Path) -> Result<(), Error> {
    private_parent(destination)?;
    if std::fs::symlink_metadata(destination).is_ok() {
        return Err(Error::Invalid("Backup destination already exists"));
    }
    let parent = destination.parent().unwrap_or(Path::new("."));
    let temp = tempfile::NamedTempFile::new_in(parent)?;
    let db = source(database)?;
    db.backup(DatabaseName::Main, temp.path(), None)?;
    temp.as_file().sync_all()?;
    temp.persist_noclobber(destination)
        .map_err(|e| Error::Io(e.error))?;
    File::open(parent)?.sync_all()?;
    Ok(())
}
/// Restore into a new path only. Validate the matching key before publishing
/// the snapshot. Replacing a live or existing database is intentionally refused.
pub fn restore_database(backup: &Path, key: [u8; 32], destination: &Path) -> Result<(), Error> {
    restore_with_retention(backup, key, destination, RetentionPolicy::default())
}
pub fn restore_with_retention(
    backup: &Path,
    key: [u8; 32],
    destination: &Path,
    retention: RetentionPolicy,
) -> Result<(), Error> {
    private_parent(destination)?;
    if std::fs::symlink_metadata(destination).is_ok() {
        return Err(Error::Invalid("Restore destination already exists"));
    }
    let parent = destination.parent().unwrap_or(Path::new("."));
    let staging = tempfile::Builder::new()
        .permissions({
            use std::os::unix::fs::PermissionsExt;
            std::fs::Permissions::from_mode(0o700)
        })
        .tempdir_in(parent)?;
    let staged = staging.path().join("verified.sqlite");
    backup_database(backup, &staged)?;
    let timezone = source(&staged)?.query_row("SELECT data FROM document WHERE id=1", [], |r| {
        r.get::<_, String>(0)
    })?;
    let document: crate::Document = serde_json::from_str(&timezone)?;
    let engine = Engine::open_with_retention(&staged, key, &document.timezone, retention)?;
    drop(engine);
    backup_database(&staged, destination)
}

/// Validate a consistent private staging copy. Checking a schema-1 database must
/// not migrate the caller's source, even when the new engine supports migration.
pub fn check_database(
    database: &Path,
    key: [u8; 32],
    timezone: &str,
    retention: RetentionPolicy,
) -> Result<(u32, u64), Error> {
    let db = source(database)?;
    let schema = db.query_row("SELECT version FROM schema_version", [], |r| r.get(0))?;
    drop(db);
    let parent = database.parent().unwrap_or(Path::new("."));
    let staging = tempfile::Builder::new()
        .permissions({
            use std::os::unix::fs::PermissionsExt;
            std::fs::Permissions::from_mode(0o700)
        })
        .tempdir_in(parent)?;
    let staged = staging.path().join("check.sqlite");
    backup_database(database, &staged)?;
    let engine = Engine::open_with_retention(&staged, key, timezone, retention)?;
    Ok((schema, engine.revision()))
}

/// Create a schema-compatible rollback candidate only while the live database is
/// stopped and its canonical policy and quota ledgers still match the snapshot.
/// Audit/receipt history may differ; preserve the current database for investigation.
/// The original snapshot schema is copied, never downgraded in place.
pub fn rollback_database(
    snapshot: &Path,
    current: &Path,
    key: [u8; 32],
    timezone: &str,
    destination: &Path,
    retention: RetentionPolicy,
) -> Result<(), Error> {
    use fs2::FileExt;
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    private_parent(current)?;
    private_parent(destination)?;
    if std::fs::symlink_metadata(destination).is_ok() {
        return Err(Error::Invalid("Rollback destination already exists"));
    }
    let mut name = current.as_os_str().to_owned();
    name.push(".lock");
    let lock = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(Path::new(&name))?;
    let metadata = lock.metadata()?;
    if !metadata.is_file()
        || metadata.uid() != unsafe { libc::geteuid() }
        || metadata.mode() & 0o077 != 0
    {
        return Err(Error::Invalid("Unsafe rollback lock"));
    }
    lock.try_lock_exclusive().map_err(|_| {
        Error::Invalid("Current database is in use; stop the agent before rollback")
    })?;
    check_database(snapshot, key, timezone, retention.clone())?;
    check_database(current, key, timezone, retention)?;
    if rollback_state(snapshot)? != rollback_state(current)? {
        return Err(Error::Invalid("Rollback would discard changed policy or quota charges; reconcile before restoring access"));
    }
    backup_database(snapshot, destination)
}

fn rollback_state(path: &Path) -> Result<(Vec<u8>, Vec<u8>), Error> {
    let db = source(path)?;
    let document: String =
        db.query_row("SELECT data FROM document WHERE id=1", [], |r| r.get(0))?;
    let document: crate::Document = serde_json::from_str(&document)?;
    let mut query = db.prepare(
        "SELECT user_id,period_id,charged,confirmed FROM ledger WHERE charged<>0 OR confirmed<>0 ORDER BY user_id,period_id",
    )?;
    let rows = query.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, u64>(2)?,
            r.get::<_, u64>(3)?,
        ))
    })?;
    let ledger = rows.collect::<Result<Vec<_>, _>>()?;
    Ok((serde_json::to_vec(&document)?, serde_json::to_vec(&ledger)?))
}
