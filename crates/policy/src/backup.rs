//! Host administrator utilities. Backups contain encrypted credentials and remain private.
use crate::{Engine, Error};
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
    if version != 1 {
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
    let engine = Engine::open_in_timezone(&staged, key, &document.timezone)?;
    drop(engine);
    backup_database(&staged, destination)
}
