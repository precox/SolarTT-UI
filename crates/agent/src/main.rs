use rand::{rngs::OsRng, RngCore};
use serde::Deserialize;
use solartt_control_api::{
    Command, Info, Request, Response, ResultData, API_VERSION, MAX_FRAME_BYTES,
};
use solartt_policy::{Engine, RetentionPolicy};
use std::{
    io,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    net::{UnixListener, UnixStream},
    sync::Semaphore,
};
use trusttunnel::{
    core::Core,
    settings::{Settings, TlsHostsSettings},
    shutdown::Shutdown,
};

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    database: PathBuf,
    encryption_key: PathBuf,
    control_socket: PathBuf,
    endpoint_settings: PathBuf,
    tls_hosts: PathBuf,
    allowed_uids: Vec<u32>,
    hostname: String,
    address: String,
    #[serde(default)]
    dns_upstreams: Vec<String>,
    #[serde(default = "default_timezone")]
    period_timezone: String,
    #[serde(default)]
    denied_addresses: Vec<std::net::IpAddr>,
    #[serde(default)]
    retention: RetentionPolicy,
}
fn default_timezone() -> String {
    "UTC".into()
}
fn private_file(path: &Path) -> io::Result<Vec<u8>> {
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.mode() & 0o077 != 0 || meta.uid() != unsafe { libc::geteuid() } {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "Key must be an owned private regular file",
        ));
    }
    use std::io::Read;
    let mut bytes = vec![];
    file.take(65).read_to_end(&mut bytes)?;
    Ok(bytes)
}
fn load(config: &Config) -> io::Result<(Settings, TlsHostsSettings)> {
    let settings: Settings = toml::from_str(&std::fs::read_to_string(&config.endpoint_settings)?)
        .map_err(|_| io::Error::other("Invalid endpoint settings"))?;
    if !settings.get_listen_address().ip().is_loopback()
        || *settings.get_ipv6_available()
        || *settings.get_allow_private_network_connections()
        || settings.get_icmp().is_some()
        || settings.get_listen_protocols().quic.is_some()
        || settings.get_listen_protocols().http2.is_none()
        || !matches!(
            settings.get_forward_protocol(),
            trusttunnel::settings::ForwardProtocolSettings::Direct(_)
        )
        || !settings.get_clients().is_empty()
        || *settings.get_ping_enable()
        || *settings.get_speedtest_enable()
    {
        return Err(io::Error::other("Managed endpoint requires loopback, H2, direct forwarding, no static credentials, private routes, IPv6, QUIC, ICMP or helper endpoints"));
    }
    if settings
        .get_metrics()
        .as_ref()
        .is_some_and(|m| !m.get_address().ip().is_loopback())
    {
        return Err(io::Error::other("Metrics must listen on loopback"));
    }
    let tls = load_tls(config)?;
    Ok((settings, tls))
}
fn load_tls(config: &Config) -> io::Result<TlsHostsSettings> {
    toml::from_str(&std::fs::read_to_string(&config.tls_hosts)?)
        .map_err(|_| io::Error::other("Invalid TLS hosts settings"))
}
async fn process(req: Request, engine: Arc<Engine>, config: &Config, actor_uid: u32) -> Response {
    let id = req.request_id.clone();
    let result = match &req.command {
        Command::Info => ResultData::Info {
            info: Info {
                version: env!("CARGO_PKG_VERSION").into(),
                api_version: API_VERSION,
                upstream_commit: "fab5b8353a19332f935fa30869307d37d4a898d1".into(),
                capabilities: vec![
                    "users".into(),
                    "credentials".into(),
                    "payload_quota".into(),
                    "expiry".into(),
                    "individual_session_revoke".into(),
                    "profile_export".into(),
                    "manual_periods".into(),
                    "calendar_periods".into(),
                    "audit".into(),
                    "audited_profile_export".into(),
                    "bounded_storage".into(),
                    "tls_reload_signal".into(),
                ],
                readiness: true,
                period_timezone: engine.period_timezone().into(),
                storage: engine.storage_info().ok(),
            },
        },
        Command::Users { after } => {
            let users: Vec<_> = engine
                .users()
                .into_iter()
                .filter(|u| after.as_ref().is_none_or(|a| u.id > *a))
                .take(4)
                .collect();
            let next_after = if users.len() == 4 {
                users.last().map(|u| u.id.clone())
            } else {
                None
            };
            ResultData::Users { users, next_after }
        }
        Command::Audit { before } => match engine.audit(*before) {
            Ok(entries) => {
                let next_before = if entries.len() == 50 {
                    entries.last().map(|e| e.seq)
                } else {
                    None
                };
                ResultData::Audit {
                    entries,
                    next_before,
                }
            }
            Err(_) => ResultData::Error {
                code: "audit_unavailable".into(),
                message: "Audit is unavailable".into(),
            },
        },
        Command::ExportProfile { credential_id } => {
            let export_config = config.clone();
            match engine
                .export_audited(
                    req.request_id.clone(),
                    credential_id.clone(),
                    actor_uid,
                    move |username, password, label| {
                        solartt_profile_export::export(
                            &export_config.hostname,
                            &export_config.address,
                            username,
                            password,
                            label,
                            export_config.dns_upstreams.clone(),
                        )
                        .map_err(|_| solartt_policy::Error::Invalid("Profile export failed"))
                    },
                )
                .await
            {
                Ok(p) => ResultData::Profile {
                    deeplink: p.deeplink,
                    toml: p.toml,
                    qr_svg: p.qr_svg,
                },
                Err(_) => ResultData::Error {
                    code: "export_failed".into(),
                    message: "Profile is unavailable".into(),
                },
            }
        }
        _ => match engine.apply_as(req, actor_uid).await {
            Ok((m, true)) => ResultData::Applied {
                resource_id: m.resource_id,
            },
            Ok((_m, false)) => ResultData::Error {
                code: "cleanup_pending".into(),
                message:
                    "Policy saved; session cleanup is still pending. Retry the same request ID."
                        .into(),
            },
            Err(e) => ResultData::Error {
                code: match e {
                    solartt_policy::Error::RevisionConflict => "revision_conflict",
                    solartt_policy::Error::IdempotencyConflict => "idempotency_conflict",
                    solartt_policy::Error::RequestExpired => "request_expired",
                    solartt_policy::Error::PeriodLimit => "period_limit",
                    solartt_policy::Error::StoragePressure | solartt_policy::Error::Storage(_) => {
                        "storage_unavailable"
                    }
                    _ => "mutation_failed",
                }
                .into(),
                message: e.to_string(),
            },
        },
    };
    let revision = engine.revision();
    Response {
        request_id: id,
        desired_revision: revision,
        applied_revision: engine.applied_revision(),
        result,
    }
}
async fn serve(stream: UnixStream, engine: Arc<Engine>, config: Config) -> io::Result<()> {
    let uid = stream.peer_cred()?.uid();
    if uid != unsafe { libc::geteuid() } && !config.allowed_uids.contains(&uid) {
        return Err(io::ErrorKind::PermissionDenied.into());
    }
    let (rx, mut tx) = stream.into_split();
    let mut reader = BufReader::new(rx).take(MAX_FRAME_BYTES as u64 + 1);
    let mut bytes = vec![];
    tokio::time::timeout(
        Duration::from_secs(10),
        reader.read_until(b'\n', &mut bytes),
    )
    .await
    .map_err(|_| io::ErrorKind::TimedOut)??;
    if bytes.len() > MAX_FRAME_BYTES || !bytes.ends_with(b"\n") {
        return Err(io::ErrorKind::InvalidData.into());
    }
    let req: Request = serde_json::from_slice(&bytes).map_err(|_| io::ErrorKind::InvalidData)?;
    if !solartt_control_api::validate_request_id(&req.request_id) {
        return Err(io::ErrorKind::InvalidData.into());
    }
    let response = process(req, engine, &config, uid).await;
    let mut bytes = serde_json::to_vec(&response).map_err(|_| io::ErrorKind::InvalidData)?;
    bytes.push(b'\n');
    if bytes.len() > MAX_FRAME_BYTES {
        return Err(io::ErrorKind::InvalidData.into());
    }
    tokio::time::timeout(Duration::from_secs(5), tx.write_all(&bytes))
        .await
        .map_err(|_| io::ErrorKind::TimedOut)??;
    tx.shutdown().await
}
async fn control(config: Config, engine: Arc<Engine>) -> io::Result<()> {
    use std::os::unix::fs::{FileTypeExt, MetadataExt, PermissionsExt};
    if let Ok(meta) = std::fs::symlink_metadata(&config.control_socket) {
        if !meta.file_type().is_socket() || meta.uid() != unsafe { libc::geteuid() } {
            return Err(io::ErrorKind::PermissionDenied.into());
        }
        if UnixStream::connect(&config.control_socket).await.is_ok() {
            return Err(io::ErrorKind::AddrInUse.into());
        }
        std::fs::remove_file(&config.control_socket)?;
    }
    let listener = UnixListener::bind(&config.control_socket)?;
    std::fs::set_permissions(
        &config.control_socket,
        std::fs::Permissions::from_mode(0o660),
    )?;
    let slots = Arc::new(Semaphore::new(32));
    loop {
        let permit = slots
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| io::ErrorKind::Interrupted)?;
        let (stream, _) = listener.accept().await?;
        let engine = engine.clone();
        let config = config.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let _ = serve(stream, engine, config).await;
        });
    }
}
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    unsafe { libc::umask(0o077) };
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("--version") {
        println!(
            "SolarTT agent {} / TrustTunnel fab5b835",
            env!("CARGO_PKG_VERSION")
        );
        return Ok(());
    }
    if args.first().map(String::as_str) == Some("--init-key") {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        let path = args.get(1).ok_or("Encryption key path is required")?;
        let mut key = [0u8; 32];
        OsRng.fill_bytes(&mut key);
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)?;
        file.write_all(&key)?;
        file.sync_all()?;
        return Ok(());
    }
    let config_path = args
        .first()
        .ok_or("Usage: solartt-agent CONFIG.toml | --init-key PATH | --version")?;
    let config: Config = toml::from_str(&std::fs::read_to_string(config_path)?)
        .map_err(|_| "Invalid agent configuration")?;
    if config.hostname.is_empty() || config.address.is_empty() {
        return Err("Profile hostname and address are required".into());
    }
    let (settings, tls) = load(&config)?;
    let key: [u8; 32] = private_file(&config.encryption_key)?
        .try_into()
        .map_err(|_| "Encryption key must be exactly 32 bytes")?;
    let engine = Engine::open_with_retention(
        &config.database,
        key,
        &config.period_timezone,
        config.retention.clone(),
    )?;
    let mut denied_addresses = solartt_agent::local_addresses()?;
    denied_addresses.extend(config.denied_addresses.iter().copied());
    if let Ok(address) = config.address.parse::<std::net::SocketAddr>() {
        denied_addresses.insert(address.ip());
    }
    let adapter = Arc::new(solartt_agent::Adapter {
        engine: engine.clone(),
        denied_addresses,
    });
    let shutdown = Shutdown::new();
    let core = Arc::new(
        Core::new_managed(settings, adapter.clone(), tls, shutdown.clone(), adapter)
            .map_err(|_| "Endpoint initialization failed")?,
    );
    let mut hup = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::hangup())?;
    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    let api = tokio::spawn(control(config.clone(), engine.clone()));
    let maintenance = tokio::spawn({
        let e = engine.clone();
        async move {
            let mut tick = tokio::time::interval(Duration::from_secs(1));
            let mut count = 0;
            loop {
                tick.tick().await;
                e.expire();
                if e.rollover().await.is_err() {
                    eprintln!("Calendar rollover pending; retrying");
                }
                e.reconcile_applied();
                count += 1;
                if count % 60 == 0 {
                    let e = e.clone();
                    if !matches!(
                        tokio::task::spawn_blocking(move || e.maintain_storage()).await,
                        Ok(Ok(()))
                    ) {
                        eprintln!(
                            "Storage retention pending; retrying without deleting quota history"
                        );
                    }
                }
                if count % 5 == 0 {
                    let e = e.clone();
                    if !matches!(
                        tokio::task::spawn_blocking(move || e.checkpoint()).await,
                        Ok(Ok(()))
                    ) {
                        eprintln!(
                            "Storage checkpoint failed; durable quota grants remain enforced"
                        );
                    }
                }
            }
        }
    });
    let endpoint = tokio::spawn({
        let core = core.clone();
        async move { core.listen().await }
    });
    let mut endpoint = endpoint;
    let mut api = api;
    let unexpected = loop {
        tokio::select! {
            _ = &mut endpoint => break true,
            _ = &mut api => break true,
            _ = tokio::signal::ctrl_c() => break false,
            _ = term.recv() => break false,
            _ = hup.recv() => {
                if load_tls(&config).and_then(|tls|core.reload_tls_hosts_settings(tls).map_err(|_|io::Error::other("TLS validation failed"))).is_err() {
                    eprintln!("TLS reload failed; previous TLS configuration retained");
                } else { eprintln!("TLS configuration reloaded"); }
            }
        }
    };
    maintenance.abort();
    api.abort();
    let _ = engine.close().await?;
    shutdown.lock().unwrap().submit();
    if !endpoint.is_finished() {
        let _ = tokio::time::timeout(Duration::from_secs(5), &mut endpoint).await;
    }
    engine.checkpoint()?;
    let _ = std::fs::remove_file(&config.control_socket);
    if unexpected {
        return Err("A required service stopped unexpectedly".into());
    }
    Ok(())
}
