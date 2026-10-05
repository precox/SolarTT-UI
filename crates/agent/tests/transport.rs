//! Isolated, real TLS/H2 transport tests. No production credentials, listeners or routes.
use base64::{engine::general_purpose::STANDARD, Engine as _};
use bytes::{BufMut, Bytes, BytesMut};
use solartt_control_api::{Command, Request, UserPolicy};
use solartt_policy::Engine;
use std::{
    net::{Ipv4Addr, SocketAddr},
    sync::Arc,
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream, UdpSocket},
    task::JoinHandle,
};
use trusttunnel::{
    core::Core,
    settings::{Settings, TlsHostsSettings},
    shutdown::Shutdown,
};

struct Task<T>(JoinHandle<T>);
impl<T> Drop for Task<T> {
    fn drop(&mut self) {
        self.0.abort();
    }
}
struct Client {
    sender: h2::client::SendRequest<Bytes>,
    driver: Task<Result<(), h2::Error>>,
}
impl Client {
    async fn connect(addr: SocketAddr, cert: rustls::pki_types::CertificateDer<'static>) -> Self {
        let mut roots = rustls::RootCertStore::empty();
        roots.add(cert).unwrap();
        let mut config = rustls::ClientConfig::builder()
            .with_root_certificates(roots)
            .with_no_client_auth();
        config.alpn_protocols = vec![b"h2".to_vec()];
        let connector = tokio_rustls::TlsConnector::from(Arc::new(config));
        let tcp = tokio::time::timeout(Duration::from_secs(3), async {
            loop {
                match TcpStream::connect(addr).await {
                    Ok(tcp) => break tcp,
                    Err(_) => tokio::time::sleep(Duration::from_millis(10)).await,
                }
            }
        })
        .await
        .unwrap();
        let tls = connector
            .connect("fixture.example.org".try_into().unwrap(), tcp)
            .await
            .unwrap();
        let (sender, connection) = h2::client::handshake(tls).await.unwrap();
        Self {
            sender,
            driver: Task(tokio::spawn(connection)),
        }
    }
    async fn request(
        &self,
        target: &str,
        basic: &str,
    ) -> (http::StatusCode, h2::SendStream<Bytes>, h2::RecvStream) {
        let mut sender = self.sender.clone().ready().await.unwrap();
        let request = http::Request::builder()
            .method("CONNECT")
            .uri(http::Uri::builder().authority(target).build().unwrap())
            .header("proxy-authorization", format!("Basic {basic}"))
            .body(())
            .unwrap();
        let (response, send) = sender.send_request(request, false).unwrap();
        let response = tokio::time::timeout(Duration::from_secs(3), response)
            .await
            .unwrap()
            .unwrap();
        (response.status(), send, response.into_body())
    }
    async fn closed(&mut self) {
        tokio::time::timeout(Duration::from_secs(3), &mut self.driver.0)
            .await
            .expect("revoked TLS/H2 transport remained open")
            .unwrap()
            .ok();
    }
}
async fn payload(rx: &mut h2::RecvStream, size: usize) -> Vec<u8> {
    tokio::time::timeout(Duration::from_secs(3), async {
        let mut bytes = vec![];
        while bytes.len() < size {
            let chunk = rx.data().await.expect("stream closed early").unwrap();
            rx.flow_control().release_capacity(chunk.len()).unwrap();
            bytes.extend_from_slice(&chunk);
        }
        assert_eq!(bytes.len(), size);
        bytes
    })
    .await
    .unwrap()
}
async fn account(
    engine: &Arc<Engine>,
    label: &str,
    limit: Option<u64>,
) -> (String, String, String) {
    async fn apply(engine: &Arc<Engine>, command: Command) -> String {
        engine
            .apply(Request {
                request_id: format!("fixture-{}", engine.revision()),
                expected_revision: Some(engine.revision()),
                command,
            })
            .await
            .unwrap()
            .0
            .resource_id
            .unwrap()
    }
    let user = apply(
        engine,
        Command::CreateUser {
            label: label.into(),
            policy: UserPolicy {
                limit_bytes: limit,
                expires_at: None,
                reset_monthly: false,
            },
        },
    )
    .await;
    let cred = apply(
        engine,
        Command::CreateCredential {
            user_id: user.clone(),
            label: "Fixture device".into(),
        },
    )
    .await;
    let (username, secret, _) = engine.export_credential(&cred).unwrap();
    (
        user,
        cred,
        STANDARD.encode(format!("{username}:{}", secret.as_str())),
    )
}
fn udp_frame(destination: SocketAddr, data: &[u8]) -> Bytes {
    let SocketAddr::V4(destination) = destination else {
        panic!("IPv4 fixture required")
    };
    let mut out = BytesMut::new();
    out.put_u32((37 + data.len()) as u32);
    out.extend_from_slice(&[0; 12]);
    out.extend_from_slice(&Ipv4Addr::new(10, 0, 0, 2).octets());
    out.put_u16(53000);
    out.extend_from_slice(&[0; 12]);
    out.extend_from_slice(&destination.ip().octets());
    out.put_u16(destination.port());
    out.put_u8(0);
    out.extend_from_slice(data);
    out.freeze()
}
struct Fixture {
    engine: Arc<Engine>,
    address: SocketAddr,
    cert: rustls::pki_types::CertificateDer<'static>,
    tcp: SocketAddr,
    udp: SocketAddr,
    _tasks: Vec<Task<()>>,
    _core: Task<std::io::Result<()>>,
    udp_peers: Arc<std::sync::Mutex<Vec<SocketAddr>>>,
    _dir: tempfile::TempDir,
}
impl Fixture {
    async fn new() -> Self {
        Self::with_denied(Default::default()).await
    }
    async fn with_denied(denied_addresses: std::collections::HashSet<std::net::IpAddr>) -> Self {
        let _ = rustls::crypto::ring::default_provider().install_default();
        let dir = tempfile::Builder::new()
            .permissions({
                use std::os::unix::fs::PermissionsExt;
                std::fs::Permissions::from_mode(0o700)
            })
            .tempdir()
            .unwrap();
        let rcgen::CertifiedKey { cert, key_pair } =
            rcgen::generate_simple_self_signed(vec!["fixture.example.org".into()]).unwrap();
        std::fs::write(dir.path().join("cert.pem"), cert.pem()).unwrap();
        std::fs::write(dir.path().join("key.pem"), key_pair.serialize_pem()).unwrap();
        let socket = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = socket.local_addr().unwrap();
        drop(socket);
        let settings: Settings = toml::from_str(&format!(
            r#"
listen_address = "{address}"
ipv6_available = false
allow_private_network_connections = true
ping_enable = false
speedtest_enable = false
auth_failure_status_code = 404
[listen_protocols.http2]
max_concurrent_streams = 128
[forward_protocol]
direct = {{}}
"#
        ))
        .unwrap();
        let tls: TlsHostsSettings = toml::from_str(&format!(
            r#"
[[main_hosts]]
hostname = "fixture.example.org"
cert_chain_path = "{}"
private_key_path = "{}"
allowed_sni = ["fixture.example.org"]
"#,
            dir.path().join("cert.pem").display(),
            dir.path().join("key.pem").display()
        ))
        .unwrap();
        let engine = Engine::open(&dir.path().join("policy.sqlite"), [17; 32]).unwrap();
        let adapter = Arc::new(solartt_agent::Adapter {
            engine: engine.clone(),
            denied_addresses,
        });
        let core = Core::new_managed(settings, adapter.clone(), tls, Shutdown::new(), adapter)
            .unwrap_or_else(|_| panic!("Core initialization failed"));
        let core = Task(tokio::spawn(async move { core.listen().await }));
        let tcp = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let tcp_address = tcp.local_addr().unwrap();
        let tcp_task = Task(tokio::spawn(async move {
            let mut streams = tokio::task::JoinSet::new();
            loop {
                tokio::select! {
                    result = tcp.accept() => { let (mut socket, _) = result.unwrap(); streams.spawn(async move {
                        let mut bytes = [0u8;4096]; while let Ok(n) = socket.read(&mut bytes).await { if n == 0 || socket.write_all(&bytes[..n]).await.is_err() { break; } }
                    }); },
                    _ = streams.join_next(), if !streams.is_empty() => {},
                }
            }
        }));
        let udp = UdpSocket::bind("127.0.0.1:0").await.unwrap();
        let udp_address = udp.local_addr().unwrap();
        let udp_peers = Arc::new(std::sync::Mutex::new(vec![]));
        let peers = udp_peers.clone();
        let udp_task = Task(tokio::spawn(async move {
            let mut bytes = [0u8; 65535];
            loop {
                let (n, addr) = udp.recv_from(&mut bytes).await.unwrap();
                peers.lock().unwrap().push(addr);
                udp.send_to(&bytes[..n], addr).await.unwrap();
            }
        }));
        Self {
            _dir: dir,
            udp_peers,
            engine,
            address,
            cert: cert.der().clone(),
            tcp: tcp_address,
            udp: udp_address,
            _tasks: vec![tcp_task, udp_task],
            _core: core,
        }
    }
    async fn client(&self) -> Client {
        Client::connect(self.address, self.cert.clone()).await
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn real_tls_revocation_closes_a_and_preserves_b_tcp_and_udp() {
    let fixture = Fixture::new().await;
    let (user_a, _, basic_a) = account(&fixture.engine, "A", None).await;
    let (_, _, basic_b) = account(&fixture.engine, "B", None).await;
    let mut a = fixture.client().await;
    let b = fixture.client().await;
    let (status, mut a_tx, mut a_rx) = a.request(&fixture.tcp.to_string(), &basic_a).await;
    assert_eq!(status, 200);
    a_tx.send_data(Bytes::from_static(b"before"), false)
        .unwrap();
    assert_eq!(payload(&mut a_rx, 6).await, b"before");
    let (status, mut a_udp_tx, mut a_udp_rx) = a.request("_udp2", &basic_a).await;
    assert_eq!(status, 200);
    a_udp_tx
        .send_data(udp_frame(fixture.udp, b"A udp"), false)
        .unwrap();
    assert_eq!(&payload(&mut a_udp_rx, 45).await[40..], b"A udp");
    let a_udp_peer = fixture.udp_peers.lock().unwrap()[0];
    let (status, _, _) = a.request("_check", &basic_b).await;
    assert_eq!(status, 404, "one TLS transport cannot mix identities");
    let (status, mut b_tx, mut b_rx) = b.request(&fixture.tcp.to_string(), &basic_b).await;
    assert_eq!(status, 200);
    let (status, mut u_tx, mut u_rx) = b.request("_udp2", &basic_b).await;
    assert_eq!(status, 200);
    let (_, complete) = fixture
        .engine
        .apply(Request {
            request_id: "block-a".into(),
            expected_revision: Some(fixture.engine.revision()),
            command: Command::BlockUser {
                user_id: user_a.clone(),
                blocked: true,
            },
        })
        .await
        .unwrap();
    assert!(
        complete,
        "policy acknowledgement preceded transport cleanup"
    );
    a.closed().await;
    assert_eq!(
        fixture
            .engine
            .users()
            .iter()
            .find(|u| u.id == user_a)
            .unwrap()
            .active_sessions,
        0
    );
    // The revoked user's outgoing UDP socket must have been destroyed before acknowledgement.
    let probe = UdpSocket::bind(a_udp_peer)
        .await
        .expect("revoked UDP resource is still bound");
    drop(probe);
    for _ in 0..8 {
        b_tx.send_data(Bytes::from_static(b"still alive"), false)
            .unwrap();
        assert_eq!(payload(&mut b_rx, 11).await, b"still alive");
        u_tx.send_data(udp_frame(fixture.udp, b"datagram"), false)
            .unwrap();
        let response = payload(&mut u_rx, 4 + 36 + 8).await;
        assert_eq!(&response[40..], b"datagram");
    }
    let fresh = fixture.client().await;
    let (status, _, _) = fresh.request("_check", &basic_a).await;
    assert_eq!(status, 404);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn tcp_and_udp_charge_payload_both_directions_and_exhaust_only_owner() {
    let fixture = Fixture::new().await;
    let (user, _, basic) = account(&fixture.engine, "limited", Some(32)).await;
    let (_, _, other) = account(&fixture.engine, "other", None).await;
    let mut client = fixture.client().await;
    let (status, mut tx, mut rx) = client.request(&fixture.tcp.to_string(), &basic).await;
    assert_eq!(status, 200);
    tx.send_data(Bytes::from_static(b"12345678"), false)
        .unwrap();
    assert_eq!(payload(&mut rx, 8).await, b"12345678");
    let (status, mut udp_tx, mut udp_rx) = client.request("_udp2", &basic).await;
    assert_eq!(status, 200);
    // Leave two payload bytes unused, then exhaust them over TCP. This gives the
    // previous UDP reply time to reach the client before the final TLS close.
    udp_tx
        .send_data(udp_frame(fixture.udp, b"1234567"), false)
        .unwrap();
    let reply = payload(&mut udp_rx, 47).await;
    assert_eq!(&reply[40..], b"1234567");
    assert_eq!(
        fixture
            .engine
            .users()
            .iter()
            .find(|u| u.id == user)
            .unwrap()
            .confirmed_bytes,
        30
    );
    tx.send_data(Bytes::from_static(b"x"), false).unwrap();
    client.closed().await;
    let view = fixture
        .engine
        .users()
        .into_iter()
        .find(|u| u.id == user)
        .unwrap();
    assert_eq!(view.confirmed_bytes, 32);
    assert_eq!(view.status, "quota_exhausted");
    let b = fixture.client().await;
    let (status, _, _) = b.request("_check", &other).await;
    assert_eq!(status, 200);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn empty_users_reject_check_and_managed_destination_deny_applies_after_dns() {
    let fixture = Fixture::with_denied(["127.0.0.1".parse().unwrap()].into_iter().collect()).await;
    let client = fixture.client().await;
    let (status, _, _) = client.request("_check", "eDp4").await;
    assert_eq!(status, 404);
    let (_, _, basic) = account(&fixture.engine, "fixture", None).await;
    for target in [
        fixture.tcp.to_string(),
        format!("localhost:{}", fixture.tcp.port()),
    ] {
        let (status, _, _) = client.request(&target, &basic).await;
        assert_ne!(
            status, 200,
            "denied destination reached through managed forwarding"
        );
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rotation_targets_one_profile_and_expiry_closes_remaining_user_transports() {
    let fixture = Fixture::new().await;
    let (user, credential_a, basic_a) = account(&fixture.engine, "shared user", None).await;
    let credential_b = fixture
        .engine
        .apply(Request {
            request_id: "issue-b".into(),
            expected_revision: Some(fixture.engine.revision()),
            command: Command::CreateCredential {
                user_id: user.clone(),
                label: "B".into(),
            },
        })
        .await
        .unwrap()
        .0
        .resource_id
        .unwrap();
    let (username, password, _) = fixture.engine.export_credential(&credential_b).unwrap();
    let basic_b = STANDARD.encode(format!("{username}:{}", password.as_str()));
    let mut a = fixture.client().await;
    let mut b = fixture.client().await;
    assert_eq!(a.request("_check", &basic_a).await.0, 200);
    let (status, mut tx, mut rx) = b.request(&fixture.tcp.to_string(), &basic_b).await;
    assert_eq!(status, 200);
    let (_, complete) = fixture
        .engine
        .apply(Request {
            request_id: "rotate-a".into(),
            expected_revision: Some(fixture.engine.revision()),
            command: Command::RotateCredential {
                credential_id: credential_a.clone(),
            },
        })
        .await
        .unwrap();
    assert!(complete);
    a.closed().await;
    tx.send_data(Bytes::from_static(b"B survives rotation"), false)
        .unwrap();
    assert_eq!(payload(&mut rx, 19).await, b"B survives rotation");
    let fresh = fixture.client().await;
    assert_eq!(fresh.request("_check", &basic_a).await.0, 404);
    let (username, password, _) = fixture.engine.export_credential(&credential_a).unwrap();
    let rotated = STANDARD.encode(format!("{username}:{}", password.as_str()));
    assert_eq!(fresh.request("_check", &rotated).await.0, 200);
    let (_, complete) = fixture
        .engine
        .apply(Request {
            request_id: "expire-user".into(),
            expected_revision: Some(fixture.engine.revision()),
            command: Command::SetPolicy {
                user_id: user,
                policy: UserPolicy {
                    limit_bytes: None,
                    expires_at: Some(solartt_policy::now() - 1),
                    reset_monthly: false,
                },
            },
        })
        .await
        .unwrap();
    assert!(complete);
    b.closed().await;
}
