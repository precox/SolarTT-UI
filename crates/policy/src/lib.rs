//! Durable access policy. No network or database I/O in authentication.
pub mod backup;
mod calendar;
mod retention;
#[cfg(test)]
mod storage_tests;
pub use retention::RetentionPolicy;
mod store;
use base64::{
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
    Engine as _,
};
use chacha20poly1305::{
    aead::{Aead, KeyInit, Payload},
    ChaCha20Poly1305, Nonce,
};
use rand::{rngs::OsRng, RngCore};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use solartt_control_api::{Command, CredentialView, Request, UserPolicy, UserView};
use std::{
    collections::HashMap,
    io,
    path::Path,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex, RwLock, Weak,
    },
};
use tokio::sync::{watch, Notify};
use zeroize::Zeroizing;

const LEASE_BYTES: u64 = 256 * 1024;
const MAX_COUNTER: u64 = i64::MAX as u64 / 2;

#[derive(thiserror::Error, Debug)]
pub enum Error {
    #[error("Database operation failed")]
    Storage(#[from] rusqlite::Error),
    #[error("Stored data is invalid")]
    Json(#[from] serde_json::Error),
    #[error("Invalid request: {0}")]
    Invalid(&'static str),
    #[error("Resource does not exist")]
    NotFound,
    #[error("Revision changed; refresh and retry")]
    RevisionConflict,
    #[error("Request ID was reused for a different operation")]
    IdempotencyConflict,
    #[error("Request receipt expired; inspect current policy before issuing a new operation")]
    RequestExpired,
    #[error("Historical period limit reached; existing quota history is preserved")]
    PeriodLimit,
    #[error("Storage is under pressure; new durable writes are unavailable")]
    StoragePressure,
    #[error("Secret protection failed")]
    Crypto,
    #[error("Access denied")]
    Denied,
    #[error("Filesystem operation failed")]
    Io(#[from] io::Error),
}

pub fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Identity {
    pub user_id: String,
    pub credential_id: String,
    pub generation: u64,
}

#[derive(Clone, Serialize, Deserialize)]
struct Credential {
    id: String,
    label: String,
    username: String,
    generation: u64,
    secret: String,
    revoked: bool,
}
#[derive(Clone, Serialize, Deserialize)]
struct User {
    id: String,
    label: String,
    policy: UserPolicy,
    blocked: bool,
    period_id: String,
    credentials: Vec<Credential>,
    #[serde(default)]
    next_reset_at: Option<i64>,
}
#[derive(Clone, Serialize, Deserialize)]
struct Document {
    revision: u64,
    users: Vec<User>,
    #[serde(default = "default_timezone")]
    timezone: String,
    key_digest: String,
}
fn default_timezone() -> String {
    "UTC".into()
}
impl Default for Document {
    fn default() -> Self {
        Self {
            revision: 0,
            users: vec![],
            timezone: default_timezone(),
            key_digest: String::new(),
        }
    }
}
#[derive(Clone, Copy, Default)]
struct Ledger {
    charged: u64,
    confirmed: u64,
}

struct LiveState {
    user: User,
    charged: u64,
    confirmed: u64,
    available: u64,
    pending: u64,
    sessions: Vec<Weak<Session>>,
    transitioning: bool,
}
struct LiveUser {
    state: Mutex<LiveState>,
    changed: Notify,
}
struct Persistent {
    store: store::Store,
    document: Document,
}

pub struct Engine {
    persistent: Mutex<Persistent>,
    users: RwLock<HashMap<String, Arc<LiveUser>>>,
    auth: RwLock<HashMap<[u8; 32], Identity>>,
    key: Zeroizing<[u8; 32]>,
    session_changed: Arc<Notify>,
    mutations: tokio::sync::Mutex<()>,
    applied: AtomicU64,
    closing: AtomicBool,
    timezone: chrono_tz::Tz,
}

pub struct Mutation {
    pub revision: u64,
    pub resource_id: Option<String>,
    pub user_id: Option<String>,
    pub replay: bool,
}

pub struct Session {
    pub identity: Identity,
    user: Arc<LiveUser>,
    cancelled: watch::Sender<bool>,
    engine_changed: Arc<Notify>,
}

pub struct Permit {
    user: Arc<LiveUser>,
    period_id: String,
    amount: u64,
    completed: bool,
    started: bool,
}

enum Attempt {
    Permit(Permit),
    Refill,
    Wait,
    NoFit,
    Denied,
}

impl Engine {
    pub fn open(database: &Path, key: [u8; 32]) -> Result<Arc<Self>, Error> {
        Self::open_in_timezone(database, key, "UTC")
    }
    pub fn open_in_timezone(
        database: &Path,
        key: [u8; 32],
        timezone: &str,
    ) -> Result<Arc<Self>, Error> {
        Self::open_with_retention(database, key, timezone, RetentionPolicy::default())
    }
    pub fn open_with_retention(
        database: &Path,
        key: [u8; 32],
        timezone: &str,
        retention: RetentionPolicy,
    ) -> Result<Arc<Self>, Error> {
        let zone: chrono_tz::Tz = timezone
            .parse()
            .map_err(|_| Error::Invalid("Unknown period timezone"))?;
        let mut store = store::Store::open(database, retention)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(database, std::fs::Permissions::from_mode(0o600))?;
        }
        let mut document = store.load()?;
        if !store.has_document()? {
            document.timezone = timezone.into();
            document.key_digest = hex::encode(Sha256::digest(key));
            store.initialize(&document)?;
        }
        if document.key_digest != hex::encode(Sha256::digest(key)) {
            return Err(Error::Crypto);
        }
        if document.timezone != timezone {
            return Err(Error::Invalid("Timezone differs from existing database"));
        }
        let applied = document.revision;
        let mut users = HashMap::new();
        for user in &document.users {
            let ledger = store.ledger(&user.id, &user.period_id)?;
            users.insert(
                user.id.clone(),
                Arc::new(LiveUser {
                    state: Mutex::new(LiveState {
                        user: user.clone(),
                        charged: ledger.charged,
                        confirmed: ledger.confirmed,
                        available: 0,
                        pending: 0,
                        sessions: vec![],
                        transitioning: false,
                    }),
                    changed: Notify::new(),
                }),
            );
        }
        let engine = Arc::new(Self {
            persistent: Mutex::new(Persistent { store, document }),
            users: RwLock::new(users),
            auth: RwLock::new(HashMap::new()),
            key: Zeroizing::new(key),
            session_changed: Arc::new(Notify::new()),
            mutations: tokio::sync::Mutex::new(()),
            applied: AtomicU64::new(applied),
            closing: AtomicBool::new(false),
            timezone: zone,
        });
        engine.refresh_auth()?;
        {
            let mut persistent = engine.persistent.lock().unwrap();
            let document = persistent.document.clone();
            persistent.store.prepare(&document)?;
        }
        Ok(engine)
    }
    pub fn period_timezone(&self) -> &str {
        self.timezone.name()
    }
    pub fn audit(
        &self,
        before: Option<u64>,
    ) -> Result<Vec<solartt_control_api::AuditEntry>, Error> {
        self.persistent.lock().unwrap().store.audit(before)
    }
    pub fn revision(&self) -> u64 {
        self.persistent.lock().unwrap().document.revision
    }
    pub fn applied_revision(&self) -> u64 {
        self.applied.load(Ordering::Acquire)
    }
    fn pending_cleanup(&self) -> bool {
        self.users.read().unwrap().values().any(|user| {
            user.state
                .lock()
                .unwrap()
                .sessions
                .iter()
                .filter_map(Weak::upgrade)
                .any(|s| s.is_cancelled())
        })
    }
    pub fn reconcile_applied(&self) {
        if let Ok(_serial) = self.mutations.try_lock() {
            if !self.pending_cleanup() {
                self.applied.store(self.revision(), Ordering::Release);
            }
        }
    }
    fn seal(&self, credential: &Credential, secret: &str) -> Result<String, Error> {
        let mut nonce = [0u8; 12];
        OsRng.fill_bytes(&mut nonce);
        let cipher =
            ChaCha20Poly1305::new_from_slice(self.key.as_ref()).map_err(|_| Error::Crypto)?;
        let aad = format!("{}:{}", credential.id, credential.generation);
        let bytes = cipher
            .encrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: secret.as_bytes(),
                    aad: aad.as_bytes(),
                },
            )
            .map_err(|_| Error::Crypto)?;
        Ok(STANDARD.encode([nonce.as_slice(), bytes.as_slice()].concat()))
    }
    fn unseal(&self, credential: &Credential) -> Result<Zeroizing<String>, Error> {
        let bytes = STANDARD
            .decode(&credential.secret)
            .map_err(|_| Error::Crypto)?;
        if bytes.len() < 28 {
            return Err(Error::Crypto);
        }
        let cipher =
            ChaCha20Poly1305::new_from_slice(self.key.as_ref()).map_err(|_| Error::Crypto)?;
        let aad = format!("{}:{}", credential.id, credential.generation);
        let plaintext = cipher
            .decrypt(
                Nonce::from_slice(&bytes[..12]),
                Payload {
                    msg: &bytes[12..],
                    aad: aad.as_bytes(),
                },
            )
            .map_err(|_| Error::Crypto)?;
        Ok(Zeroizing::new(
            String::from_utf8(plaintext).map_err(|_| Error::Crypto)?,
        ))
    }
    fn refresh_auth(&self) -> Result<(), Error> {
        let p = self.persistent.lock().unwrap();
        let mut auth = HashMap::new();
        for u in &p.document.users {
            for c in u.credentials.iter().filter(|c| !c.revoked) {
                let password = self.unseal(c)?;
                let plain = Zeroizing::new(format!("{}:{}", c.username, password.as_str()));
                let basic = Zeroizing::new(STANDARD.encode(plain.as_bytes()));
                auth.insert(
                    Sha256::digest(basic.as_bytes()).into(),
                    Identity {
                        user_id: u.id.clone(),
                        credential_id: c.id.clone(),
                        generation: c.generation,
                    },
                );
            }
        }
        *self.auth.write().unwrap() = auth;
        Ok(())
    }
    pub fn authenticate(&self, basic: &str) -> Option<Identity> {
        if self.closing.load(Ordering::Acquire) {
            return None;
        }
        if basic.len() > 2048 {
            return None;
        }
        let key: [u8; 32] = Sha256::digest(basic.as_bytes()).into();
        let identity = self.auth.read().unwrap().get(&key)?.clone();
        let user = self.users.read().unwrap().get(&identity.user_id)?.clone();
        let state = user.state.lock().unwrap();
        if !state.transitioning && state.permitted() && state.valid_credential(&identity) {
            Some(identity)
        } else {
            None
        }
    }
    pub fn open_session(&self, identity: Identity) -> Result<Arc<Session>, Error> {
        if self.closing.load(Ordering::Acquire) {
            return Err(Error::Denied);
        }
        let user = self
            .users
            .read()
            .unwrap()
            .get(&identity.user_id)
            .cloned()
            .ok_or(Error::Denied)?;
        let mut state = user.state.lock().unwrap();
        state.sessions.retain(|s| s.strong_count() > 0);
        if state.transitioning
            || !state.permitted()
            || !state.valid_credential(&identity)
            || state.sessions.len() >= 32
        {
            return Err(Error::Denied);
        }
        let (cancelled, _) = watch::channel(false);
        let session = Arc::new(Session {
            identity,
            user: user.clone(),
            cancelled,
            engine_changed: self.session_changed.clone(),
        });
        state.sessions.push(Arc::downgrade(&session));
        Ok(session)
    }
    pub fn users(&self) -> Vec<UserView> {
        let users = self.users.read().unwrap();
        let mut result: Vec<_> = users
            .values()
            .map(|user| {
                let mut s = user.state.lock().unwrap();
                s.sessions.retain(|x| x.strong_count() > 0);
                let credentials = s
                    .user
                    .credentials
                    .iter()
                    .map(|c| CredentialView {
                        id: c.id.clone(),
                        label: c.label.clone(),
                        username: c.username.clone(),
                        generation: c.generation,
                        revoked: c.revoked,
                        active_sessions: s
                            .sessions
                            .iter()
                            .filter_map(Weak::upgrade)
                            .filter(|x| x.identity.credential_id == c.id)
                            .count(),
                    })
                    .collect();
                UserView {
                    id: s.user.id.clone(),
                    label: s.user.label.clone(),
                    policy: s.user.policy.clone(),
                    status: s.status().into(),
                    period_id: s.user.period_id.clone(),
                    next_reset_at: s.user.next_reset_at,
                    charged_bytes: s.charged,
                    confirmed_bytes: s.confirmed,
                    available_lease_bytes: s.available,
                    pending_bytes: s.pending,
                    active_sessions: s.sessions.len(),
                    credentials,
                }
            })
            .collect();
        result.sort_by(|a, b| a.id.cmp(&b.id));
        result
    }
    pub fn export_credential(
        &self,
        id: &str,
    ) -> Result<(String, Zeroizing<String>, String), Error> {
        let p = self.persistent.lock().unwrap();
        for u in &p.document.users {
            if let Some(c) = u.credentials.iter().find(|c| c.id == id && !c.revoked) {
                return Ok((c.username.clone(), self.unseal(c)?, u.label.clone()));
            }
        }
        Err(Error::NotFound)
    }
    /// Record preparation (or denial) durably before a secret-bearing result leaves the engine.
    /// The caller UID is supplied by the peer credential check, never from JSON.
    pub async fn export_audited<T, F>(
        self: &Arc<Self>,
        request_id: String,
        credential_id: String,
        actor_uid: u32,
        build: F,
    ) -> Result<T, Error>
    where
        T: Send + 'static,
        F: FnOnce(&str, &str, &str) -> Result<T, Error> + Send + 'static,
    {
        if !solartt_control_api::validate_request_id(&request_id) {
            return Err(Error::Invalid("Invalid request ID"));
        }
        let engine = self.clone();
        tokio::spawn(async move {
            let _serial = engine.mutations.lock().await;
            if engine.closing.load(Ordering::Acquire) {
                return Err(Error::Denied);
            }
            let worker = engine.clone();
            tokio::task::spawn_blocking(move || {
                let persistent = worker.persistent.lock().unwrap();
                let found = persistent.document.users.iter().find_map(|user| {
                    user.credentials
                        .iter()
                        .find(|credential| credential.id == credential_id && !credential.revoked)
                        .map(|credential| (user.id.clone(), user.label.clone(), credential.clone()))
                });
                drop(persistent);
                let user_id = found.as_ref().map(|(id, _, _)| id.as_str());
                let result = match &found {
                    Some((_, label, credential)) => worker
                        .unseal(credential)
                        .and_then(|password| build(&credential.username, password.as_str(), label)),
                    None => Err(Error::NotFound),
                };
                let safe_credential = uuid::Uuid::parse_str(&credential_id)
                    .ok()
                    .map(|id| id.to_string());
                let mut persistent = worker.persistent.lock().unwrap();
                let revision = persistent.document.revision;
                persistent.store.record_export(
                    revision,
                    user_id,
                    if result.is_ok() {
                        "profile_export_prepared"
                    } else {
                        "profile_export_denied"
                    },
                    store::AuditContext {
                        request_id: &request_id,
                        actor_uid: Some(actor_uid),
                        credential_id: safe_credential.as_deref(),
                    },
                )?;
                result
            })
            .await
            .map_err(|_| Error::Invalid("Export worker failed"))?
        })
        .await
        .map_err(|_| Error::Invalid("Export task failed"))?
    }
    pub fn storage_info(&self) -> Result<solartt_control_api::StorageInfo, Error> {
        self.persistent.lock().unwrap().store.storage_info()
    }
    pub fn maintain_storage(&self) -> Result<(), Error> {
        self.persistent.lock().unwrap().store.maintain(now())
    }
    fn mutate(&self, request: &Request, actor_uid: Option<u32>) -> Result<Mutation, Error> {
        if !solartt_control_api::validate_request_id(&request.request_id)
            || !request.command.mutates()
        {
            return Err(Error::Invalid("Invalid mutation"));
        }
        let fingerprint = hex::encode(Sha256::digest(serde_json::to_vec(&request.command)?));
        let mut p = self.persistent.lock().unwrap();
        if let Some(previous) = p.store.previous(&request.request_id, &fingerprint)? {
            return Ok(previous);
        }
        if p.store.request_expired(request.expected_revision)? {
            return Err(Error::RequestExpired);
        }
        if request.expected_revision != Some(p.document.revision) {
            return Err(Error::RevisionConflict);
        }
        let mut document = p.document.clone();
        let mut resource_id = None;
        let user_id;
        let operation;
        match &request.command {
            Command::CreateUser { label, policy } => {
                validate_policy(policy)?;
                validate_label(label)?;
                let id = uuid::Uuid::new_v4().to_string();
                if document.users.len() >= 256 {
                    return Err(Error::Invalid("Too many users"));
                }
                document.users.push(User {
                    id: id.clone(),
                    label: label.clone(),
                    policy: policy.clone(),
                    blocked: false,
                    period_id: if policy.reset_monthly {
                        calendar::period(self.timezone, now())?.0
                    } else {
                        "initial".into()
                    },
                    next_reset_at: if policy.reset_monthly {
                        Some(calendar::period(self.timezone, now())?.1)
                    } else {
                        None
                    },
                    credentials: vec![],
                });
                resource_id = Some(id.clone());
                user_id = Some(id);
                operation = "create_user";
            }
            Command::SetPolicy {
                user_id: id,
                policy,
            } => {
                validate_policy(policy)?;
                let u = find_user(&mut document, id)?;
                if policy.reset_monthly && !u.policy.reset_monthly {
                    u.next_reset_at = Some(calendar::period(self.timezone, now())?.1);
                }
                if !policy.reset_monthly {
                    u.next_reset_at = None;
                }
                u.policy = policy.clone();
                user_id = Some(id.clone());
                operation = "set_policy";
            }
            Command::BlockUser {
                user_id: id,
                blocked,
            } => {
                find_user(&mut document, id)?.blocked = *blocked;
                user_id = Some(id.clone());
                operation = "block_user";
            }
            Command::CreateCredential { user_id: id, label } => {
                validate_label(label)?;
                let u = find_user(&mut document, id)?;
                if u.credentials.len() >= 16 {
                    return Err(Error::Invalid("Too many credentials"));
                }
                let cid = uuid::Uuid::new_v4().to_string();
                let mut c = Credential {
                    id: cid.clone(),
                    label: label.clone(),
                    username: format!("solar_{}", uuid::Uuid::new_v4().simple()),
                    generation: 1,
                    secret: String::new(),
                    revoked: false,
                };
                c.secret = self.seal(&c, random_secret().as_str())?;
                u.credentials.push(c);
                resource_id = Some(cid);
                user_id = Some(id.clone());
                operation = "create_credential";
            }
            Command::RotateCredential { credential_id }
            | Command::RevokeCredential { credential_id } => {
                let (u, c) = document
                    .users
                    .iter_mut()
                    .find_map(|u| {
                        let id = u.id.clone();
                        u.credentials
                            .iter_mut()
                            .find(|c| c.id == *credential_id)
                            .map(|c| (id, c))
                    })
                    .ok_or(Error::NotFound)?;
                c.generation = c
                    .generation
                    .checked_add(1)
                    .ok_or(Error::Invalid("Generation overflow"))?;
                c.revoked = matches!(request.command, Command::RevokeCredential { .. });
                if !c.revoked {
                    c.secret = self.seal(c, random_secret().as_str())?;
                }
                user_id = Some(u);
                resource_id = Some(credential_id.clone());
                operation = "credential_change";
            }
            Command::StartPeriod { .. } => {
                return Err(Error::Invalid("Use asynchronous period transition"))
            }
            _ => return Err(Error::Invalid("Unsupported mutation")),
        }
        document.revision = document
            .revision
            .checked_add(1)
            .ok_or(Error::Invalid("Revision overflow"))?;
        p.store.save_mutation(
            &document,
            &fingerprint,
            resource_id.as_deref(),
            user_id.as_deref(),
            operation,
            store::AuditContext {
                request_id: &request.request_id,
                actor_uid,
                credential_id: match &request.command {
                    Command::RotateCredential { credential_id }
                    | Command::RevokeCredential { credential_id } => Some(credential_id),
                    Command::CreateCredential { .. } => resource_id.as_deref(),
                    _ => None,
                },
            },
        )?;
        p.document = document.clone();
        drop(p);
        self.apply_document(&document)?;
        self.refresh_auth()?;
        Ok(Mutation {
            revision: document.revision,
            resource_id,
            user_id,
            replay: false,
        })
    }
    /// Serialize mutations, pause new permits during policy/period transitions,
    /// and report applied only after cancelled transports have released ownership.
    pub async fn apply(self: &Arc<Self>, request: Request) -> Result<(Mutation, bool), Error> {
        self.apply_at(request, now(), false, None).await
    }
    pub async fn apply_as(
        self: &Arc<Self>,
        request: Request,
        actor_uid: u32,
    ) -> Result<(Mutation, bool), Error> {
        self.apply_at(request, now(), false, Some(actor_uid)).await
    }
    // Dropping an API/maintenance caller must not cancel an in-progress commit,
    // release its serialization lock early, or leave permit admission paused.
    async fn apply_at(
        self: &Arc<Self>,
        request: Request,
        timestamp: i64,
        automatic: bool,
        actor_uid: Option<u32>,
    ) -> Result<(Mutation, bool), Error> {
        let engine = self.clone();
        tokio::spawn(async move {
            engine
                .apply_inner(request, timestamp, automatic, actor_uid)
                .await
        })
        .await
        .map_err(|_| Error::Invalid("Mutation task failed"))?
    }
    async fn apply_inner(
        self: &Arc<Self>,
        request: Request,
        timestamp: i64,
        automatic: bool,
        actor_uid: Option<u32>,
    ) -> Result<(Mutation, bool), Error> {
        let _serial = self.mutations.lock().await;
        if self.closing.load(Ordering::Acquire) {
            return Err(Error::Denied);
        }
        let transition_id = match &request.command {
            Command::SetPolicy { user_id, .. } | Command::StartPeriod { user_id, .. } => {
                Some(user_id.clone())
            }
            _ => None,
        };
        let transition = transition_id
            .as_ref()
            .and_then(|id| self.users.read().unwrap().get(id).cloned());
        if let Some(user) = &transition {
            user.state.lock().unwrap().transitioning = true;
            let wait = async {
                loop {
                    let n = user.changed.notified();
                    tokio::pin!(n);
                    n.as_mut().enable();
                    if user.state.lock().unwrap().pending == 0 {
                        break;
                    }
                    n.await;
                }
            };
            if tokio::time::timeout(std::time::Duration::from_secs(2), wait)
                .await
                .is_err()
            {
                user.state.lock().unwrap().transitioning = false;
                user.changed.notify_waiters();
                return Err(Error::Invalid(
                    "Active byte permits prevented policy transition",
                ));
            }
        }
        let engine = self.clone();
        let result = tokio::task::spawn_blocking(move || {
            if matches!(request.command, Command::StartPeriod { .. }) {
                engine.start_period(&request, timestamp, automatic, actor_uid)
            } else {
                if let Command::SetPolicy { user_id, .. } = &request.command {
                    engine.return_unused(user_id)?;
                }
                engine.mutate(&request, actor_uid)
            }
        })
        .await
        .map_err(|_| Error::Invalid("Policy worker failed"));
        if let Some(user) = transition {
            user.state.lock().unwrap().transitioning = false;
            user.changed.notify_waiters();
        }
        let mutation = result??;
        let complete = if let Some(id) = &mutation.user_id {
            self.wait_revoked(id, std::time::Duration::from_secs(2))
                .await
        } else {
            true
        };
        if complete && !self.pending_cleanup() {
            self.applied.store(self.revision(), Ordering::Release);
        }
        Ok((mutation, complete))
    }
    fn start_period(
        &self,
        request: &Request,
        timestamp: i64,
        automatic: bool,
        actor_uid: Option<u32>,
    ) -> Result<Mutation, Error> {
        let Command::StartPeriod { user_id, period_id } = &request.command else {
            return Err(Error::Invalid("Not a period transition"));
        };
        if !solartt_control_api::validate_request_id(&request.request_id)
            || !solartt_control_api::validate_request_id(period_id)
        {
            return Err(Error::Invalid("Invalid period or request ID"));
        }
        let fingerprint = hex::encode(Sha256::digest(serde_json::to_vec(&request.command)?));
        let user = self
            .users
            .read()
            .unwrap()
            .get(user_id)
            .cloned()
            .ok_or(Error::NotFound)?;
        let mut state = user.state.lock().unwrap();
        if state.pending != 0 {
            return Err(Error::Invalid("Active permits at period transition"));
        }
        let mut p = self.persistent.lock().unwrap();
        if let Some(old) = p.store.previous(&request.request_id, &fingerprint)? {
            return Ok(old);
        }
        if p.store.request_expired(request.expected_revision)? {
            return Err(Error::RequestExpired);
        }
        if request.expected_revision != Some(p.document.revision) {
            return Err(Error::RevisionConflict);
        }
        if state.user.period_id == *period_id && !automatic {
            return Err(Error::Invalid("Already in requested period"));
        }
        // Returning a known unused lease is safe only while permit creation is paused.
        p.store.checkpoint(
            user_id,
            &state.user.period_id,
            state.charged - state.available,
            state.confirmed,
        )?;
        state.charged -= state.available;
        state.available = 0;
        let next = p.store.ledger(user_id, period_id)?;
        let mut document = p.document.clone();
        let u = find_user(&mut document, user_id)?;
        u.period_id = period_id.clone();
        if automatic {
            u.next_reset_at = Some(calendar::period(self.timezone, timestamp)?.1);
        }
        document.revision = document
            .revision
            .checked_add(1)
            .ok_or(Error::Invalid("Revision overflow"))?;
        p.store.save_mutation(
            &document,
            &fingerprint,
            None,
            Some(user_id),
            "start_period",
            store::AuditContext {
                request_id: &request.request_id,
                actor_uid,
                credential_id: None,
            },
        )?;
        p.document = document.clone();
        state.user = find_user(&mut document, user_id)?.clone();
        state.charged = next.charged;
        state.confirmed = next.confirmed;
        state.available = 0;
        let revision = document.revision;
        drop(p);
        drop(state);
        user.changed.notify_waiters();
        Ok(Mutation {
            revision,
            resource_id: None,
            user_id: Some(user_id.clone()),
            replay: false,
        })
    }
    fn apply_document(&self, document: &Document) -> Result<(), Error> {
        let mut users = self.users.write().unwrap();
        for u in &document.users {
            if let Some(live) = users.get(&u.id) {
                let mut s = live.state.lock().unwrap();
                s.user = u.clone();
                s.cap_available();
                for session in s.sessions.iter().filter_map(Weak::upgrade) {
                    if !s.permitted() || !s.valid_credential(&session.identity) {
                        session.cancel();
                    }
                }
                live.changed.notify_waiters();
            } else {
                users.insert(
                    u.id.clone(),
                    Arc::new(LiveUser {
                        state: Mutex::new(LiveState {
                            user: u.clone(),
                            charged: 0,
                            confirmed: 0,
                            available: 0,
                            pending: 0,
                            sessions: vec![],
                            transitioning: false,
                        }),
                        changed: Notify::new(),
                    }),
                );
            }
        }
        Ok(())
    }
    pub async fn wait_revoked(&self, user_id: &str, timeout: std::time::Duration) -> bool {
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            let notification = self.session_changed.notified();
            tokio::pin!(notification);
            notification.as_mut().enable();
            let user = self.users.read().unwrap().get(user_id).cloned();
            let Some(user) = user else {
                return true;
            };
            let remaining = user
                .state
                .lock()
                .unwrap()
                .sessions
                .iter()
                .filter_map(Weak::upgrade)
                .any(|s| s.is_cancelled());
            if !remaining {
                return true;
            }
            if tokio::time::timeout_at(deadline, notification)
                .await
                .is_err()
            {
                return false;
            }
        }
    }
    pub async fn rollover(self: &Arc<Self>) -> Result<(), Error> {
        self.rollover_at(now()).await
    }
    async fn rollover_at(self: &Arc<Self>, timestamp: i64) -> Result<(), Error> {
        let due: Vec<_> = self
            .persistent
            .lock()
            .unwrap()
            .document
            .users
            .iter()
            .filter(|u| u.policy.reset_monthly && u.next_reset_at.is_some_and(|t| t <= timestamp))
            .map(|u| (u.id.clone(), u.next_reset_at.unwrap()))
            .collect();
        for (user_id, boundary) in due {
            let period_id = calendar::period(self.timezone, timestamp)?.0;
            self.apply_at(
                Request {
                    request_id: format!("monthly_{user_id}_{boundary}"),
                    expected_revision: Some(self.revision()),
                    command: Command::StartPeriod { user_id, period_id },
                },
                timestamp,
                true,
                None,
            )
            .await?;
        }
        Ok(())
    }
    pub fn expire(&self) {
        for user in self.users.read().unwrap().values() {
            let state = user.state.lock().unwrap();
            if !state.permitted() {
                state.cancel_all();
            }
        }
    }
    pub fn checkpoint(&self) -> Result<(), Error> {
        let users: Vec<_> = self.users.read().unwrap().values().cloned().collect();
        // Lock order: live user -> database for ledger operations. Metadata never holds DB during live updates.
        for user in users {
            let state = user.state.lock().unwrap();
            self.persistent.lock().unwrap().store.checkpoint(
                &state.user.id,
                &state.user.period_id,
                state.charged,
                state.confirmed,
            )?;
        }
        Ok(())
    }
    /// Refund only a provably unused pool, with no pending write permits.
    fn return_unused(&self, id: &str) -> Result<(), Error> {
        let user = self
            .users
            .read()
            .unwrap()
            .get(id)
            .cloned()
            .ok_or(Error::NotFound)?;
        let mut state = user.state.lock().unwrap();
        if !state.transitioning || state.pending != 0 {
            return Err(Error::Invalid("User is not quiescent"));
        }
        let charged = state.charged - state.available;
        self.persistent.lock().unwrap().store.checkpoint(
            id,
            &state.user.period_id,
            charged,
            state.confirmed,
        )?;
        state.charged = charged;
        state.available = 0;
        Ok(())
    }
    /// Stop authentication, close transports, then refund known unused leases.
    /// A timeout retains outstanding leases conservatively.
    pub async fn close(self: &Arc<Self>) -> Result<bool, Error> {
        let _serial = self.mutations.lock().await;
        self.closing.store(true, Ordering::Release);
        let users: Vec<_> = self
            .users
            .read()
            .unwrap()
            .iter()
            .map(|(id, u)| (id.clone(), u.clone()))
            .collect();
        for (_, user) in &users {
            let mut state = user.state.lock().unwrap();
            state.transitioning = true;
            state.cancel_all();
            user.changed.notify_waiters();
        }
        let cleaned = tokio::time::timeout(std::time::Duration::from_secs(2), async {
            let mut poll = tokio::time::interval(std::time::Duration::from_millis(20));
            loop {
                if users.iter().all(|(_, user)| {
                    let s = user.state.lock().unwrap();
                    s.pending == 0 && s.sessions.iter().all(|s| s.strong_count() == 0)
                }) {
                    break;
                }
                poll.tick().await;
            }
        })
        .await
        .is_ok();
        for (id, user) in users {
            let quiescent = {
                let s = user.state.lock().unwrap();
                s.pending == 0 && s.sessions.iter().all(|s| s.strong_count() == 0)
            };
            if quiescent {
                self.return_unused(&id)?;
            }
        }
        self.checkpoint()?;
        Ok(cleaned)
    }
    async fn refill(self: &Arc<Self>, user: Arc<LiveUser>) -> Result<(), Error> {
        let engine = self.clone();
        tokio::task::spawn_blocking(move || {
            let mut s = user.state.lock().unwrap();
            if !s.permitted() {
                return Err(Error::Denied);
            }
            if s.transitioning {
                return Ok(());
            }
            let remaining = s
                .user
                .policy
                .limit_bytes
                .map(|limit| limit.saturating_sub(s.charged))
                .unwrap_or(LEASE_BYTES);
            let grant = LEASE_BYTES
                .saturating_sub(s.available + s.pending)
                .min(remaining)
                .min(MAX_COUNTER.saturating_sub(s.charged));
            if grant == 0 {
                return Err(Error::Denied);
            }
            engine.persistent.lock().unwrap().store.grant(
                &s.user.id,
                &s.user.period_id,
                grant,
                s.confirmed,
            )?;
            s.charged += grant;
            s.available += grant;
            user.changed.notify_waiters();
            Ok(())
        })
        .await
        .map_err(|_| Error::Invalid("Storage worker failed"))?
    }
    pub async fn reserve(
        self: &Arc<Self>,
        session: &Arc<Session>,
        amount: usize,
        datagram: bool,
    ) -> io::Result<Permit> {
        if amount == 0 || (datagram && amount > 65535) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Empty reservation",
            ));
        }
        loop {
            let notification = session.user.changed.notified();
            tokio::pin!(notification);
            notification.as_mut().enable();
            let result = {
                let mut s = session.user.state.lock().unwrap();
                if session.is_cancelled()
                    || !s.permitted()
                    || !s.valid_credential(&session.identity)
                {
                    Attempt::Denied
                } else if s.transitioning {
                    Attempt::Wait
                } else {
                    let remaining = s
                        .user
                        .policy
                        .limit_bytes
                        .map(|l| l.saturating_sub(s.charged))
                        .unwrap_or(LEASE_BYTES);
                    if remaining > 0
                        && s.available + s.pending < LEASE_BYTES
                        && (s.available == 0 || (datagram && amount as u64 > s.available))
                    {
                        Attempt::Refill
                    } else if datagram && amount as u64 > s.available {
                        if s.pending > 0 {
                            Attempt::Wait
                        } else {
                            Attempt::NoFit
                        }
                    } else if s.available == 0 {
                        if s.pending > 0 {
                            Attempt::Wait
                        } else {
                            Attempt::Denied
                        }
                    } else {
                        let n = (amount as u64).min(s.available);
                        s.available -= n;
                        s.pending += n;
                        Attempt::Permit(Permit {
                            user: session.user.clone(),
                            period_id: s.user.period_id.clone(),
                            amount: n,
                            completed: false,
                            started: false,
                        })
                    }
                }
            };
            match result {
                Attempt::Permit(p) => return Ok(p),
                Attempt::Denied => {
                    return Err(io::Error::new(
                        io::ErrorKind::PermissionDenied,
                        "Access denied",
                    ))
                }
                Attempt::NoFit => {
                    return Err(io::Error::new(
                        io::ErrorKind::WouldBlock,
                        "Datagram exceeds remaining quota",
                    ))
                }
                Attempt::Refill => self
                    .refill(session.user.clone())
                    .await
                    .map_err(|_| io::Error::other("Quota storage unavailable"))?,
                Attempt::Wait => {
                    tokio::select! { _=session.cancelled()=>return Err(io::ErrorKind::PermissionDenied.into()), _=notification=>{} }
                }
            }
        }
    }
}

impl LiveState {
    fn cap_available(&mut self) {
        if let Some(limit) = self.user.policy.limit_bytes {
            // Include unknown writes in consumption, not only confirmed bytes.
            let cap = limit.saturating_sub(self.charged - self.available);
            self.available = self.available.min(cap);
        }
    }
    fn valid_credential(&self, identity: &Identity) -> bool {
        self.user.credentials.iter().any(|c| {
            c.id == identity.credential_id && c.generation == identity.generation && !c.revoked
        })
    }
    fn exhausted(&self) -> bool {
        self.user
            .policy
            .limit_bytes
            .is_some_and(|l| self.charged >= l && self.available == 0 && self.pending == 0)
    }
    fn permitted(&self) -> bool {
        !self.user.blocked
            && self.user.policy.expires_at.is_none_or(|t| t > now())
            && !self.exhausted()
    }
    fn status(&self) -> &'static str {
        if self.user.blocked {
            "blocked"
        } else if self.user.policy.expires_at.is_some_and(|t| t <= now()) {
            "expired"
        } else if self.exhausted() {
            "quota_exhausted"
        } else {
            "active"
        }
    }
    fn cancel_all(&self) {
        for session in self.sessions.iter().filter_map(Weak::upgrade) {
            session.cancel();
        }
    }
}
impl Session {
    pub fn is_cancelled(&self) -> bool {
        *self.cancelled.borrow()
    }
    pub fn cancel(&self) {
        self.cancelled.send_replace(true);
        self.user.changed.notify_waiters();
    }
    pub async fn cancelled(&self) {
        let mut rx = self.cancelled.subscribe();
        loop {
            if *rx.borrow_and_update() {
                return;
            }
            if rx.changed().await.is_err() {
                return;
            }
        }
    }
}
impl Drop for Session {
    fn drop(&mut self) {
        self.engine_changed.notify_waiters();
    }
}
impl Permit {
    pub fn amount(&self) -> usize {
        self.amount as usize
    }
    /// A cancelled asynchronous write may already have transmitted data.
    pub fn begin(&mut self) {
        self.started = true;
    }
    pub fn finish(mut self, sent: usize) -> io::Result<()> {
        if sent as u64 > self.amount {
            return Err(io::Error::other("Invalid transmitted count"));
        }
        let mut s = self.user.state.lock().unwrap();
        if s.user.period_id != self.period_id {
            return Err(io::Error::other(
                "Quota period changed with an active permit",
            ));
        }
        s.pending -= self.amount;
        s.available += self.amount - sent as u64;
        s.confirmed += sent as u64;
        s.cap_available();
        self.completed = true;
        if s.exhausted() {
            s.cancel_all();
        }
        self.user.changed.notify_waiters();
        Ok(())
    }
}
impl Drop for Permit {
    fn drop(&mut self) {
        if !self.completed {
            let mut s = self.user.state.lock().unwrap();
            if s.user.period_id == self.period_id {
                s.pending -= self.amount;
                if !self.started {
                    s.available += self.amount;
                    s.cap_available();
                }
                if s.exhausted() {
                    s.cancel_all();
                }
            }
            self.user.changed.notify_waiters();
        }
    }
}
fn random_secret() -> Zeroizing<String> {
    let mut bytes = Zeroizing::new([0u8; 32]);
    OsRng.fill_bytes(bytes.as_mut());
    Zeroizing::new(URL_SAFE_NO_PAD.encode(bytes.as_ref()))
}
fn validate_label(s: &str) -> Result<(), Error> {
    if s.trim().is_empty() || s.len() > 128 || s.chars().any(char::is_control) {
        Err(Error::Invalid("Invalid label"))
    } else {
        Ok(())
    }
}
fn validate_policy(p: &UserPolicy) -> Result<(), Error> {
    if p.limit_bytes.is_some_and(|n| n > MAX_COUNTER) {
        Err(Error::Invalid("Quota is too large"))
    } else {
        Ok(())
    }
}
fn find_user<'a>(d: &'a mut Document, id: &str) -> Result<&'a mut User, Error> {
    d.users
        .iter_mut()
        .find(|u| u.id == id)
        .ok_or(Error::NotFound)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    fn fixture() -> (tempfile::TempDir, Arc<Engine>) {
        let dir = tempfile::Builder::new()
            .permissions({
                use std::os::unix::fs::PermissionsExt;
                std::fs::Permissions::from_mode(0o700)
            })
            .tempdir()
            .unwrap();
        let engine = Engine::open(&dir.path().join("policy.sqlite"), [9; 32]).unwrap();
        (dir, engine)
    }
    fn request(e: &Engine, command: Command) -> Request {
        Request {
            request_id: uuid::Uuid::new_v4().to_string(),
            expected_revision: Some(e.revision()),
            command,
        }
    }
    async fn account(e: &Arc<Engine>, limit: Option<u64>) -> Arc<Session> {
        let user = e
            .apply(request(
                e,
                Command::CreateUser {
                    label: "Synthetic test".into(),
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
        let cred = e
            .apply(request(
                e,
                Command::CreateCredential {
                    user_id: user,
                    label: "Device".into(),
                },
            ))
            .await
            .unwrap()
            .0
            .resource_id
            .unwrap();
        let (login, password, _) = e.export_credential(&cred).unwrap();
        let basic = STANDARD.encode(format!("{}:{}", login, password.as_str()));
        e.open_session(e.authenticate(&basic).unwrap()).unwrap()
    }
    #[tokio::test]
    async fn refunds_dropped_and_partial_writes_without_double_charge() {
        let (_dir, e) = fixture();
        let session = account(&e, Some(10)).await;
        let p = e.reserve(&session, 10, false).await.unwrap();
        p.finish(3).unwrap();
        let p = e.reserve(&session, 4, true).await.unwrap();
        drop(p);
        let p = e.reserve(&session, 10, false).await.unwrap();
        assert_eq!(p.amount(), 7);
        p.finish(7).unwrap();
        assert!(session.is_cancelled());
        assert_eq!(e.users()[0].confirmed_bytes, 10);
        assert!(e.reserve(&session, 1, false).await.is_err());
    }
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn concurrent_directions_share_exactly_one_budget() {
        let (_dir, e) = fixture();
        let session = account(&e, Some(101)).await;
        let delivered = Arc::new(AtomicU64::new(0));
        let mut tasks = vec![];
        // Establish every transport before the first writer can exhaust quota.
        let sessions: Vec<_> = (0..20)
            .map(|_| e.open_session(session.identity.clone()).unwrap())
            .collect();
        for session in sessions {
            let e = e.clone();
            // Each worker represents a separate transport/device of this user.
            let delivered = delivered.clone();
            tasks.push(tokio::spawn(async move {
                while let Ok(p) = e.reserve(&session, 1, false).await {
                    delivered.fetch_add(1, Ordering::SeqCst);
                    p.finish(1).unwrap();
                }
            }));
        }
        for t in tasks {
            tokio::time::timeout(std::time::Duration::from_secs(3), t)
                .await
                .unwrap()
                .unwrap();
        }
        assert_eq!(delivered.load(Ordering::SeqCst), 101);
        assert_eq!(e.users()[0].confirmed_bytes, 101);
    }
    #[tokio::test]
    async fn oversized_datagram_does_not_consume_residual_quota() {
        let (_dir, e) = fixture();
        let session = account(&e, Some(5)).await;
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(1),
            e.reserve(&session, 6, true),
        )
        .await
        .unwrap();
        assert_eq!(result.err().unwrap().kind(), io::ErrorKind::WouldBlock);
        assert!(!session.is_cancelled());
        let p = e.reserve(&session, 5, true).await.unwrap();
        p.finish(5).unwrap();
        assert_eq!(e.users()[0].confirmed_bytes, 5);
    }
    #[tokio::test]
    async fn refills_an_insufficient_udp_lease_without_busy_loop() {
        let (_dir, e) = fixture();
        let session = account(&e, Some(LEASE_BYTES * 2)).await;
        let p = e
            .reserve(&session, LEASE_BYTES as usize - 10, false)
            .await
            .unwrap();
        p.finish(LEASE_BYTES as usize - 10).unwrap();
        let p = tokio::time::timeout(
            std::time::Duration::from_secs(1),
            e.reserve(&session, 100, true),
        )
        .await
        .unwrap()
        .unwrap();
        p.finish(100).unwrap();
        let s = e.users();
        assert!(s[0].available_lease_bytes + s[0].pending_bytes <= LEASE_BYTES);
    }
    #[tokio::test]
    async fn revoking_a_preserves_b_and_ack_waits_for_a_cleanup() {
        let (_dir, e) = fixture();
        let a = account(&e, None).await;
        let b = account(&e, None).await;
        let req = request(
            &e,
            Command::BlockUser {
                user_id: a.identity.user_id.clone(),
                blocked: true,
            },
        );
        let worker = e.clone();
        let apply = tokio::spawn(async move { worker.apply(req).await });
        tokio::time::timeout(std::time::Duration::from_secs(1), a.cancelled())
            .await
            .unwrap();
        assert!(!b.is_cancelled());
        let p = e.reserve(&b, 1, false).await.unwrap();
        p.finish(1).unwrap();
        assert!(!apply.is_finished());
        drop(a);
        assert!(apply.await.unwrap().unwrap().1);
    }
    #[tokio::test]
    async fn restart_cannot_recover_an_unknown_outstanding_lease() {
        let (dir, e) = fixture();
        let s = account(&e, Some(LEASE_BYTES * 2)).await;
        let cred = s.identity.credential_id.clone();
        let p = e.reserve(&s, 100, false).await.unwrap();
        p.finish(100).unwrap();
        let charged = e.users()[0].charged_bytes;
        assert_eq!(charged, LEASE_BYTES);
        drop(s);
        drop(e);
        let resumed = Engine::open(&dir.path().join("policy.sqlite"), [9; 32]).unwrap();
        assert_eq!(resumed.users()[0].charged_bytes, charged);
        assert_eq!(resumed.users()[0].available_lease_bytes, 0);
        let (login, password, _) = resumed.export_credential(&cred).unwrap();
        let basic = STANDARD.encode(format!("{}:{}", login, password.as_str()));
        let session = resumed
            .open_session(resumed.authenticate(&basic).unwrap())
            .unwrap();
        let p = resumed
            .reserve(&session, LEASE_BYTES as usize * 2, false)
            .await
            .unwrap();
        assert_eq!(p.amount(), LEASE_BYTES as usize);
        let n = p.amount();
        p.finish(n).unwrap();
    }
    #[tokio::test]
    async fn period_switch_retains_transport_and_reusing_a_period_retains_spend() {
        let (_dir, e) = fixture();
        let s = account(&e, Some(100)).await;
        let user = s.identity.user_id.clone();
        let p = e.reserve(&s, 30, false).await.unwrap();
        p.finish(30).unwrap();
        e.apply(request(
            &e,
            Command::StartPeriod {
                user_id: user.clone(),
                period_id: "next".into(),
            },
        ))
        .await
        .unwrap();
        assert!(!s.is_cancelled());
        assert_eq!(e.users()[0].confirmed_bytes, 0);
        let p = e.reserve(&s, 20, false).await.unwrap();
        p.finish(20).unwrap();
        e.apply(request(
            &e,
            Command::StartPeriod {
                user_id: user,
                period_id: "initial".into(),
            },
        ))
        .await
        .unwrap();
        assert_eq!(e.users()[0].confirmed_bytes, 30);
        assert_eq!(e.users()[0].charged_bytes, 30);
    }
    #[tokio::test]
    async fn idempotency_replays_and_conflicting_ids_are_rejected() {
        let (_dir, e) = fixture();
        let req = request(
            &e,
            Command::CreateUser {
                label: "Fixture".into(),
                policy: UserPolicy {
                    limit_bytes: Some(0),
                    expires_at: None,
                    reset_monthly: false,
                },
            },
        );
        let first = e.apply(req.clone()).await.unwrap().0;
        let second = e.apply(req.clone()).await.unwrap().0;
        assert!(second.replay);
        assert_eq!(first.resource_id, second.resource_id);
        assert_eq!(e.users().len(), 1);
        let other = Request {
            command: Command::BlockUser {
                user_id: first.resource_id.unwrap(),
                blocked: true,
            },
            ..req
        };
        assert!(matches!(
            e.apply(other).await,
            Err(Error::IdempotencyConflict)
        ));
    }
    #[tokio::test]
    async fn credentials_are_encrypted_and_wrong_key_fails_closed() {
        let (dir, e) = fixture();
        let s = account(&e, None).await;
        let (_, secret, _) = e.export_credential(&s.identity.credential_id).unwrap();
        e.checkpoint().unwrap();
        let db = std::fs::read(dir.path().join("policy.sqlite")).unwrap();
        assert!(!db.windows(secret.len()).any(|w| w == secret.as_bytes()));
        drop(s);
        drop(e);
        assert!(Engine::open(&dir.path().join("policy.sqlite"), [8; 32]).is_err());
    }
    #[tokio::test]
    async fn cancelled_started_write_is_never_refunded() {
        let (_dir, e) = fixture();
        let s = account(&e, Some(10)).await;
        let mut permit = e.reserve(&s, 4, false).await.unwrap();
        permit.begin();
        drop(permit);
        let permit = e.reserve(&s, 10, false).await.unwrap();
        assert_eq!(permit.amount(), 6);
        permit.finish(6).unwrap();
        assert!(s.is_cancelled());
        assert_eq!(e.users()[0].confirmed_bytes, 6);
        assert_eq!(e.users()[0].charged_bytes, 10);
    }
    #[tokio::test]
    async fn lowering_quota_preserves_unknown_writes_across_restart() {
        let (dir, e) = fixture();
        let s = account(&e, Some(100)).await;
        let mut permit = e.reserve(&s, 10, false).await.unwrap();
        permit.begin();
        drop(permit);
        let user_id = s.identity.user_id.clone();
        e.apply(request(
            &e,
            Command::SetPolicy {
                user_id,
                policy: UserPolicy {
                    limit_bytes: Some(15),
                    expires_at: None,
                    reset_monthly: false,
                },
            },
        ))
        .await
        .unwrap();
        let permit = e.reserve(&s, 100, false).await.unwrap();
        assert_eq!(permit.amount(), 5);
        permit.finish(5).unwrap();
        drop(s);
        e.checkpoint().unwrap();
        drop(e);
        let e = Engine::open(&dir.path().join("policy.sqlite"), [9; 32]).unwrap();
        assert_eq!(e.users()[0].charged_bytes, 15);
        assert_eq!(e.users()[0].status, "quota_exhausted");
    }
    #[tokio::test]
    async fn clean_shutdown_refunds_unused_pool_and_denies_new_authentication() {
        let (dir, e) = fixture();
        let s = account(&e, Some(100)).await;
        e.reserve(&s, 10, false).await.unwrap().finish(10).unwrap();
        let id = s.identity.clone();
        drop(s);
        assert!(e.close().await.unwrap());
        assert!(e.open_session(id).is_err());
        drop(e);
        let e = Engine::open(&dir.path().join("policy.sqlite"), [9; 32]).unwrap();
        assert_eq!(e.users()[0].charged_bytes, 10);
        assert_eq!(e.users()[0].confirmed_bytes, 10);
    }
    #[tokio::test]
    async fn monthly_rollover_is_persistent_idempotent_and_retains_live_transport() {
        let (dir, e) = fixture();
        let session = account(&e, Some(100)).await;
        let id = session.identity.user_id.clone();
        e.reserve(&session, 10, false)
            .await
            .unwrap()
            .finish(10)
            .unwrap();
        e.apply(request(
            &e,
            Command::SetPolicy {
                user_id: id.clone(),
                policy: UserPolicy {
                    limit_bytes: Some(100),
                    expires_at: None,
                    reset_monthly: true,
                },
            },
        ))
        .await
        .unwrap();
        let next = e.users()[0].next_reset_at.unwrap();
        e.rollover_at(next).await.unwrap();
        let revision = e.revision();
        assert_eq!(e.users()[0].confirmed_bytes, 0);
        assert!(!session.is_cancelled());
        e.reserve(&session, 7, false)
            .await
            .unwrap()
            .finish(7)
            .unwrap();
        e.rollover_at(next + 10).await.unwrap();
        assert_eq!(e.revision(), revision);
        assert_eq!(e.users()[0].confirmed_bytes, 7);
        let entries = e.audit(None).unwrap();
        assert_eq!(
            entries
                .iter()
                .filter(|a| a.operation == "start_period")
                .count(),
            1
        );
        drop(session);
        e.close().await.unwrap();
        drop(e);
        let e = Engine::open(&dir.path().join("policy.sqlite"), [9; 32]).unwrap();
        e.rollover_at(next + 10).await.unwrap();
        assert_eq!(e.users()[0].confirmed_bytes, 7);
        assert_eq!(e.revision(), revision);
        drop(e);
        assert!(Engine::open_in_timezone(
            &dir.path().join("policy.sqlite"),
            [9; 32],
            "Europe/Moscow"
        )
        .is_err());
    }
    #[tokio::test]
    async fn manually_selected_calendar_period_advances_schedule_without_refunding_spend() {
        let (_dir, e) = fixture();
        let session = account(&e, Some(100)).await;
        let user_id = session.identity.user_id.clone();
        e.apply(request(
            &e,
            Command::SetPolicy {
                user_id: user_id.clone(),
                policy: UserPolicy {
                    limit_bytes: Some(100),
                    expires_at: None,
                    reset_monthly: true,
                },
            },
        ))
        .await
        .unwrap();
        let boundary = e.users()[0].next_reset_at.unwrap();
        let (period_id, next_boundary) = calendar::period(e.timezone, boundary).unwrap();
        e.apply(request(&e, Command::StartPeriod { user_id, period_id }))
            .await
            .unwrap();
        e.reserve(&session, 7, false)
            .await
            .unwrap()
            .finish(7)
            .unwrap();
        e.rollover_at(boundary).await.unwrap();
        assert_eq!(e.users()[0].next_reset_at, Some(next_boundary));
        assert_eq!(e.users()[0].confirmed_bytes, 7);
        assert!(!session.is_cancelled());
        let revision = e.revision();
        e.rollover_at(boundary + 1).await.unwrap();
        assert_eq!(e.revision(), revision);
    }
    #[tokio::test]
    async fn disconnecting_api_caller_does_not_cancel_policy_commit() {
        let (_dir, e) = fixture();
        let session = account(&e, Some(100)).await;
        let permit = e.reserve(&session, 1, false).await.unwrap();
        let req = request(
            &e,
            Command::SetPolicy {
                user_id: session.identity.user_id.clone(),
                policy: UserPolicy {
                    limit_bytes: Some(200),
                    expires_at: None,
                    reset_monthly: false,
                },
            },
        );
        let wanted = e.revision() + 1;
        let engine = e.clone();
        let caller = tokio::spawn(async move { engine.apply(req).await });
        tokio::time::timeout(std::time::Duration::from_secs(1), async {
            while !session.user.state.lock().unwrap().transitioning {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        caller.abort();
        drop(permit);
        tokio::time::timeout(std::time::Duration::from_secs(1), async {
            while e.revision() != wanted {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_eq!(e.reserve(&session, 1, false).await.unwrap().amount(), 1);
    }
    #[tokio::test]
    async fn live_wal_backup_restore_preserves_policy_charge_and_key_validation() {
        let (dir, e) = fixture();
        let session = account(&e, Some(100)).await;
        e.reserve(&session, 10, false)
            .await
            .unwrap()
            .finish(10)
            .unwrap();
        e.checkpoint().unwrap();
        let snapshot = dir.path().join("snapshot.sqlite");
        backup::backup_database(&dir.path().join("policy.sqlite"), &snapshot).unwrap();
        assert!(backup::backup_database(&dir.path().join("policy.sqlite"), &snapshot).is_err());
        let failed = dir.path().join("failed.sqlite");
        assert!(backup::restore_database(&snapshot, [8; 32], &failed).is_err());
        assert!(!failed.exists());
        let restored = dir.path().join("restored.sqlite");
        backup::restore_database(&snapshot, [9; 32], &restored).unwrap();
        let copy = Engine::open(&restored, [9; 32]).unwrap();
        assert_eq!(copy.revision(), e.revision());
        assert_eq!(copy.users()[0].confirmed_bytes, 10);
        assert_eq!(copy.users()[0].charged_bytes, 100);
        assert_eq!(copy.users()[0].status, "quota_exhausted");
        let (username, secret, _) = copy
            .export_credential(&session.identity.credential_id)
            .unwrap();
        let (_, original, _) = e
            .export_credential(&session.identity.credential_id)
            .unwrap();
        assert!(!username.is_empty());
        assert_eq!(secret.as_str(), original.as_str());
    }
    #[test]
    fn second_agent_and_future_schema_are_rejected_without_modifying_data() {
        let (dir, e) = fixture();
        assert!(Engine::open(&dir.path().join("policy.sqlite"), [9; 32]).is_err());
        drop(e);
        let db = rusqlite::Connection::open(dir.path().join("policy.sqlite")).unwrap();
        db.execute("UPDATE schema_version SET version=999", [])
            .unwrap();
        drop(db);
        assert!(Engine::open(&dir.path().join("policy.sqlite"), [9; 32]).is_err());
        let db = rusqlite::Connection::open(dir.path().join("policy.sqlite")).unwrap();
        assert_eq!(
            db.query_row("SELECT version FROM schema_version", [], |r| r
                .get::<_, u32>(0))
                .unwrap(),
            999
        );
    }
    #[test]
    fn empty_database_also_rejects_a_mismatched_master_key() {
        let (dir, e) = fixture();
        drop(e);
        assert!(matches!(
            Engine::open(&dir.path().join("policy.sqlite"), [8; 32]),
            Err(Error::Crypto)
        ));
    }
    #[test]
    fn empty_users_never_authenticate() {
        let (_dir, e) = fixture();
        assert!(e.authenticate("anything").is_none());
    }
}
