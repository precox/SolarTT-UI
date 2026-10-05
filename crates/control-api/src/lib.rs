//! Versioned, bounded control protocol. Profile-bearing responses are secrets.
use serde::{Deserialize, Serialize};

pub const API_VERSION: u32 = 1;
pub const MAX_FRAME_BYTES: usize = 128 * 1024;

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub request_id: String,
    pub expected_revision: Option<u64>,
    pub command: Command,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum Command {
    Info,
    Users { after: Option<String> },
    Audit { before: Option<u64> },
    CreateUser { label: String, policy: UserPolicy },
    SetPolicy { user_id: String, policy: UserPolicy },
    BlockUser { user_id: String, blocked: bool },
    CreateCredential { user_id: String, label: String },
    RotateCredential { credential_id: String },
    RevokeCredential { credential_id: String },
    StartPeriod { user_id: String, period_id: String },
    ExportProfile { credential_id: String },
}

impl Command {
    pub fn mutates(&self) -> bool {
        !matches!(
            self,
            Self::Info | Self::Users { .. } | Self::Audit { .. } | Self::ExportProfile { .. }
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UserPolicy {
    /// None is explicit unlimited access. Zero means no traffic allowance.
    pub limit_bytes: Option<u64>,
    pub expires_at: Option<i64>,
    #[serde(default)]
    pub reset_monthly: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CredentialView {
    pub id: String,
    pub label: String,
    pub username: String,
    pub generation: u64,
    pub revoked: bool,
    pub active_sessions: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct UserView {
    pub id: String,
    pub label: String,
    pub policy: UserPolicy,
    pub status: String,
    pub period_id: String,
    pub next_reset_at: Option<i64>,
    /// Durable quota charge: confirmed + leases whose use is not yet finalized.
    pub charged_bytes: u64,
    pub confirmed_bytes: u64,
    pub available_lease_bytes: u64,
    pub pending_bytes: u64,
    pub active_sessions: usize,
    pub credentials: Vec<CredentialView>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AuditEntry {
    pub seq: u64,
    pub timestamp: i64,
    pub revision: u64,
    pub operation: String,
    pub subject: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Info {
    pub version: String,
    pub api_version: u32,
    pub upstream_commit: String,
    pub capabilities: Vec<String>,
    pub readiness: bool,
    pub period_timezone: String,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Response {
    pub request_id: String,
    pub desired_revision: u64,
    pub applied_revision: u64,
    pub result: ResultData,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ResultData {
    Info {
        info: Info,
    },
    Users {
        users: Vec<UserView>,
        next_after: Option<String>,
    },
    Audit {
        entries: Vec<AuditEntry>,
        next_before: Option<u64>,
    },
    Applied {
        resource_id: Option<String>,
    },
    Profile {
        deeplink: String,
        toml: String,
        qr_svg: String,
    },
    Error {
        code: String,
        message: String,
    },
}

pub fn validate_request_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 80
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_unknown_mutation_fields() {
        let value = r#"{"op":"block_user","user_id":"a","blocked":true,"shell":"x"}"#;
        assert!(serde_json::from_str::<Command>(value).is_err());
    }
    #[test]
    fn zero_and_unlimited_are_distinct() {
        let zero = UserPolicy {
            limit_bytes: Some(0),
            expires_at: None,
            reset_monthly: false,
        };
        let unlimited = UserPolicy {
            limit_bytes: None,
            expires_at: None,
            reset_monthly: false,
        };
        assert_ne!(
            serde_json::to_string(&zero).unwrap(),
            serde_json::to_string(&unlimited).unwrap()
        );
    }
}
