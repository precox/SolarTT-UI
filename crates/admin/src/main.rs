//! Explicit host administrator operations; never invoked by the web panel.
use rand::{rngs::OsRng, RngCore};
use solartt_policy::{backup, RetentionPolicy};
use std::{
    io::{Read, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::Path,
};
fn key(path: &Path) -> Result<[u8; 32], Box<dyn std::error::Error>> {
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0 {
        return Err("Key must be an owned private regular file".into());
    }
    let mut bytes = vec![];
    file.take(33).read_to_end(&mut bytes)?;
    bytes
        .try_into()
        .map_err(|_| "Key must contain exactly 32 bytes".into())
}
fn retention(path: &str) -> Result<RetentionPolicy, Box<dyn std::error::Error>> {
    toml::from_str(&std::fs::read_to_string(path)?)
        .map_err(|_| "Invalid storage-retention configuration".into())
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    unsafe { libc::umask(0o077) };
    let args: Vec<_> = std::env::args().skip(1).collect();
    match args.iter().map(String::as_str).collect::<Vec<_>>().as_slice() {
        ["--version"]=>println!("SolarTT admin {}",env!("CARGO_PKG_VERSION")),
        ["init-key",path]=>{let mut bytes=[0u8;32];OsRng.fill_bytes(&mut bytes);let mut file=std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(path)?;file.write_all(&bytes)?;file.sync_all()?;},
        ["backup",database,destination]=>{backup::backup_database(Path::new(database),Path::new(destination))?;println!("Private SQLite snapshot created. Preserve its matching encryption key separately.");},
        ["restore",snapshot,key_path,destination]=>{backup::restore_database(Path::new(snapshot),key(Path::new(key_path))?,Path::new(destination))?;println!("Validated snapshot restored into a new database path.");},
        ["check",database,key_path,timezone]=>{let (schema,revision)=backup::check_database(Path::new(database),key(Path::new(key_path))?,timezone,RetentionPolicy::default())?;println!("Database and key valid; source schema {schema}, policy revision {revision}. Source unchanged.");},
        ["check",database,key_path,timezone,policy]=>{let retention=retention(policy)?;let (schema,revision)=backup::check_database(Path::new(database),key(Path::new(key_path))?,timezone,retention)?;println!("Database and key valid; source schema {schema}, policy revision {revision}. Source unchanged.");},
        ["restore",snapshot,key_path,destination,policy]=>{let retention=retention(policy)?;backup::restore_with_retention(Path::new(snapshot),key(Path::new(key_path))?,Path::new(destination),retention)?;println!("Validated snapshot restored into a new database path.");},
        ["rollback",snapshot,current,key_path,timezone,destination]=>{backup::rollback_database(Path::new(snapshot),Path::new(current),key(Path::new(key_path))?,timezone,Path::new(destination),RetentionPolicy::default())?;println!("Compatible rollback candidate created; keep services stopped while switching binaries/configuration. Preserve the current database.");},
        ["rollback",snapshot,current,key_path,timezone,destination,policy]=>{backup::rollback_database(Path::new(snapshot),Path::new(current),key(Path::new(key_path))?,timezone,Path::new(destination),retention(policy)?)?;println!("Compatible rollback candidate created; keep services stopped while switching binaries/configuration. Preserve the current database.");},
        _=>return Err("Usage: solartt-admin init-key PATH | backup DB NEW_SNAPSHOT | restore SNAPSHOT KEY NEW_DB [RETENTION.toml] | check DB KEY TIMEZONE [RETENTION.toml] | rollback SNAPSHOT CURRENT_DB KEY TIMEZONE NEW_DB [RETENTION.toml] | --version".into()),
    }
    Ok(())
}
