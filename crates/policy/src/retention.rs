use crate::Error;
use serde::{Deserialize, Serialize};

/// Host-owned limits. Ledger entries are never deleted by retention.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct RetentionPolicy {
    pub audit_max_rows: u32,
    pub audit_max_days: u32,
    pub request_max_rows: u32,
    pub request_max_days: u32,
    pub periods_per_user: u32,
    pub database_max_bytes: u64,
    pub wal_max_bytes: u64,
}

impl Default for RetentionPolicy {
    fn default() -> Self {
        Self {
            audit_max_rows: 10_000,
            audit_max_days: 90,
            request_max_rows: 4_096,
            request_max_days: 7,
            periods_per_user: 256,
            database_max_bytes: 64 * 1024 * 1024,
            wal_max_bytes: 16 * 1024 * 1024,
        }
    }
}

impl RetentionPolicy {
    pub(crate) fn validate(&self) -> Result<(), Error> {
        if !(1..=100_000).contains(&self.audit_max_rows)
            || !(1..=100_000).contains(&self.request_max_rows)
            || !(1..=3650).contains(&self.audit_max_days)
            || !(1..=3650).contains(&self.request_max_days)
            || !(1..=4096).contains(&self.periods_per_user)
            || !(256 * 1024..=1024 * 1024 * 1024).contains(&self.database_max_bytes)
            || !(4096..=256 * 1024 * 1024).contains(&self.wal_max_bytes)
        {
            return Err(Error::Invalid("Invalid storage retention limits"));
        }
        Ok(())
    }
}
