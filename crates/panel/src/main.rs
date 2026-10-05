use argon2::{
    password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString},
    Argon2,
};
use axum::{
    extract::{DefaultBodyLimit, Request, State},
    http::{header, HeaderMap, HeaderValue, StatusCode},
    middleware::{self, Next},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use rand::{rngs::OsRng, RngCore};
use serde::Deserialize;
use solartt_control_api::{
    Request as ControlRequest, Response as ControlResponse, MAX_FRAME_BYTES,
};
use std::{
    collections::{HashMap, VecDeque},
    net::SocketAddr,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    listen: SocketAddr,
    public_origin: String,
    control_socket: PathBuf,
    admin_username: String,
    password_hash_file: PathBuf,
}
struct Session {
    csrf: String,
    expires: Instant,
}
struct App {
    config: Config,
    hash: String,
    sessions: Mutex<HashMap<String, Session>>,
    attempts: Mutex<VecDeque<Instant>>,
    login_slots: Arc<tokio::sync::Semaphore>,
    secure_cookie: bool,
    host: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Login {
    username: String,
    password: String,
}
fn random_token() -> String {
    let mut bytes = [0u8; 32];
    OsRng.fill_bytes(&mut bytes);
    hex::encode(bytes)
}
fn cookie(headers: &HeaderMap) -> Option<String> {
    headers
        .get(header::COOKIE)?
        .to_str()
        .ok()?
        .split(';')
        .find_map(|s| s.trim().strip_prefix("solartt_session=").map(str::to_owned))
}
fn authenticated(app: &App, headers: &HeaderMap) -> Option<String> {
    let token = cookie(headers)?;
    let mut sessions = app.sessions.lock().unwrap();
    sessions.retain(|_, s| s.expires > Instant::now());
    sessions.get(&token).map(|s| s.csrf.clone())
}
fn error(code: StatusCode, message: &str) -> Response {
    (code, Json(serde_json::json!({"error":message}))).into_response()
}
async fn security(State(app): State<Arc<App>>, request: Request, next: Next) -> Response {
    if request
        .headers()
        .get(header::HOST)
        .and_then(|h| h.to_str().ok())
        != Some(app.host.as_str())
    {
        return error(StatusCode::BAD_REQUEST, "Unexpected host");
    }
    if request.method() != axum::http::Method::GET
        && request.method() != axum::http::Method::HEAD
        && request
            .headers()
            .get(header::ORIGIN)
            .and_then(|h| h.to_str().ok())
            != Some(app.config.public_origin.as_str())
    {
        return error(StatusCode::FORBIDDEN, "Unexpected origin");
    }
    let mut response = next.run(request).await;
    let headers = response.headers_mut();
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    headers.insert(
        "x-content-type-options",
        HeaderValue::from_static("nosniff"),
    );
    headers.insert("referrer-policy", HeaderValue::from_static("no-referrer"));
    headers.insert("content-security-policy",HeaderValue::from_static("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"));
    response
}
async fn login(State(app): State<Arc<App>>, Json(login): Json<Login>) -> Response {
    if login.username.len() > 128 || login.password.len() > 1024 {
        return error(StatusCode::UNAUTHORIZED, "Invalid credentials");
    }
    {
        let mut attempts = app.attempts.lock().unwrap();
        attempts.retain(|t| t.elapsed() < Duration::from_secs(60));
        if attempts.len() >= 12 {
            return error(StatusCode::TOO_MANY_REQUESTS, "Wait before retrying");
        }
        attempts.push_back(Instant::now());
    }
    let Ok(_slot) = app.login_slots.clone().try_acquire_owned() else {
        return error(StatusCode::TOO_MANY_REQUESTS, "Wait before retrying");
    };
    let hash = app.hash.clone();
    let expected = app.config.admin_username.clone();
    let valid = tokio::task::spawn_blocking(move || {
        let verified = PasswordHash::new(&hash).ok().is_some_and(|hash| {
            Argon2::default()
                .verify_password(login.password.as_bytes(), &hash)
                .is_ok()
        });
        verified && login.username == expected
    })
    .await
    .unwrap_or(false);
    if !valid {
        return error(StatusCode::UNAUTHORIZED, "Invalid credentials");
    }
    let token = random_token();
    let csrf = random_token();
    {
        let mut sessions = app.sessions.lock().unwrap();
        sessions.retain(|_, s| s.expires > Instant::now());
        if sessions.len() >= 128 {
            return error(
                StatusCode::TOO_MANY_REQUESTS,
                "Too many active administrator sessions",
            );
        }
        sessions.insert(
            token.clone(),
            Session {
                csrf: csrf.clone(),
                expires: Instant::now() + Duration::from_secs(12 * 3600),
            },
        );
    }
    let mut response = Json(serde_json::json!({"csrf":csrf})).into_response();
    let secure = if app.secure_cookie { "; Secure" } else { "" };
    response.headers_mut().insert(
        header::SET_COOKIE,
        HeaderValue::from_str(&format!(
            "solartt_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200{secure}"
        ))
        .unwrap(),
    );
    response
}
async fn session(State(app): State<Arc<App>>, headers: HeaderMap) -> Response {
    match authenticated(&app, &headers) {
        Some(csrf) => Json(serde_json::json!({"csrf":csrf})).into_response(),
        None => error(StatusCode::UNAUTHORIZED, "Sign in required"),
    }
}
async fn logout(State(app): State<Arc<App>>, headers: HeaderMap) -> Response {
    let Some(csrf) = authenticated(&app, &headers) else {
        return error(StatusCode::UNAUTHORIZED, "Sign in required");
    };
    if headers.get("x-csrf-token").and_then(|s| s.to_str().ok()) != Some(csrf.as_str()) {
        return error(StatusCode::FORBIDDEN, "CSRF check failed");
    }
    if let Some(token) = cookie(&headers) {
        app.sessions.lock().unwrap().remove(&token);
    }
    let mut response = StatusCode::NO_CONTENT.into_response();
    response.headers_mut().insert(
        header::SET_COOKIE,
        HeaderValue::from_static("solartt_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"),
    );
    response
}
async fn control(config: &Config, request: &ControlRequest) -> Result<ControlResponse, ()> {
    let mut stream = tokio::net::UnixStream::connect(&config.control_socket)
        .await
        .map_err(|_| ())?;
    let mut bytes = serde_json::to_vec(request).map_err(|_| ())?;
    bytes.push(b'\n');
    if bytes.len() > MAX_FRAME_BYTES {
        return Err(());
    }
    stream.write_all(&bytes).await.map_err(|_| ())?;
    let mut reader = BufReader::new(stream).take(MAX_FRAME_BYTES as u64 + 1);
    let mut bytes = vec![];
    reader.read_until(b'\n', &mut bytes).await.map_err(|_| ())?;
    if bytes.len() > MAX_FRAME_BYTES || !bytes.ends_with(b"\n") {
        return Err(());
    }
    serde_json::from_slice(&bytes).map_err(|_| ())
}
async fn command(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
    Json(req): Json<ControlRequest>,
) -> Response {
    let Some(csrf) = authenticated(&app, &headers) else {
        return error(StatusCode::UNAUTHORIZED, "Sign in required");
    };
    // Every command endpoint requires CSRF, including secret-bearing profile export.
    if headers.get("x-csrf-token").and_then(|s| s.to_str().ok()) != Some(csrf.as_str()) {
        return error(StatusCode::FORBIDDEN, "CSRF check failed");
    }
    if !solartt_control_api::validate_request_id(&req.request_id) {
        return error(StatusCode::BAD_REQUEST, "Invalid request ID");
    }
    match tokio::time::timeout(Duration::from_secs(15), control(&app.config, &req)).await {
        Ok(Ok(response)) => Json(response).into_response(),
        _ => error(
            StatusCode::SERVICE_UNAVAILABLE,
            "Agent unavailable. Retry using the same request ID.",
        ),
    }
}
async fn index() -> Html<&'static str> {
    Html(include_str!("../assets/index.html"))
}
async fn javascript() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/javascript; charset=utf-8")],
        include_str!("../assets/app.js"),
    )
}
async fn css() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/css; charset=utf-8")],
        include_str!("../assets/style.css"),
    )
}

fn normalize_origin(config: &mut Config) -> Result<(String, bool), Box<dyn std::error::Error>> {
    if !config.listen.ip().is_loopback() {
        return Err("Panel must bind loopback; expose through an HTTPS reverse proxy".into());
    }
    let origin = url::Url::parse(&config.public_origin)?;
    let host = origin.host_str().ok_or("Public origin requires a host")?;
    let secure_cookie = origin.scheme() == "https";
    let local = host == "localhost"
        || host
            .trim_matches(['[', ']'])
            .parse::<std::net::IpAddr>()
            .is_ok_and(|ip| ip.is_loopback());
    if !(secure_cookie || origin.scheme() == "http" && local)
        || origin.path() != "/"
        || origin.query().is_some()
        || origin.fragment().is_some()
        || !origin.username().is_empty()
        || origin.password().is_some()
    {
        return Err("Public origin must be an HTTPS origin or loopback HTTP origin".into());
    }
    let host = origin[url::Position::BeforeHost..url::Position::AfterPort].to_owned();
    config.public_origin = origin.origin().ascii_serialization();
    Ok((host, secure_cookie))
}

fn router(app: Arc<App>) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/assets/app.js", get(javascript))
        .route("/assets/style.css", get(css))
        .route("/api/login", post(login))
        .route("/api/session", get(session))
        .route("/api/logout", post(logout))
        .route("/api/command", post(command))
        .layer(DefaultBodyLimit::max(64 * 1024))
        .layer(middleware::from_fn_with_state(app.clone(), security))
        .with_state(app)
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("--version") {
        println!("SolarTT panel {}", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }
    if args.first().map(String::as_str) == Some("--init-admin") {
        use std::io::{Read, Write};
        use std::os::unix::fs::OpenOptionsExt;
        let path = args.get(1).ok_or("Password hash path is required")?;
        let mut input = String::new();
        std::io::stdin().take(1025).read_to_string(&mut input)?;
        let password = input.trim_end_matches(['\n', '\r']);
        if password.len() < 12 || password.len() > 1024 {
            return Err("Administrator password must contain 12–1024 bytes".into());
        }
        let salt = SaltString::generate(&mut OsRng);
        let hash = Argon2::default()
            .hash_password(password.as_bytes(), &salt)
            .map_err(|_| "Hash generation failed")?
            .to_string();
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)?;
        file.write_all(hash.as_bytes())?;
        file.sync_all()?;
        return Ok(());
    }
    let config: Config = toml::from_str(&std::fs::read_to_string(
        args.first()
            .ok_or("Usage: solartt-panel CONFIG.toml | --init-admin PATH | --version")?,
    )?)?;
    let mut config = config;
    let (host, secure_cookie) = normalize_origin(&mut config)?;
    use std::io::Read;
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(&config.password_hash_file)?;
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != unsafe { libc::geteuid() }
    {
        return Err("Administrator hash must be an owned private regular file".into());
    }
    let mut hash = String::new();
    file.take(1025).read_to_string(&mut hash)?;
    if hash.len() > 1024 {
        return Err("Administrator hash is too large".into());
    }
    PasswordHash::new(hash.trim()).map_err(|_| "Invalid administrator password hash")?;
    let listen = config.listen;
    let app = Arc::new(App {
        hash: hash.trim().into(),
        config,
        sessions: Mutex::new(HashMap::new()),
        attempts: Mutex::new(VecDeque::new()),
        login_slots: Arc::new(tokio::sync::Semaphore::new(2)),
        secure_cookie,
        host,
    });
    let router = router(app);
    axum::serve(tokio::net::TcpListener::bind(listen).await?, router).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{body::Body, http::Request};
    use tower::ServiceExt;
    fn app(origin: &str) -> Arc<App> {
        let mut config = Config {
            listen: "127.0.0.1:8081".parse().unwrap(),
            public_origin: origin.into(),
            control_socket: "/nonexistent-fixture/socket".into(),
            admin_username: "operator".into(),
            password_hash_file: "unused".into(),
        };
        let (host, secure_cookie) = normalize_origin(&mut config).unwrap();
        let hash = Argon2::default()
            .hash_password(
                b"synthetic-test-password",
                &SaltString::generate(&mut OsRng),
            )
            .unwrap()
            .to_string();
        Arc::new(App {
            config,
            host,
            secure_cookie,
            hash,
            sessions: Mutex::new(HashMap::new()),
            attempts: Mutex::new(VecDeque::new()),
            login_slots: Arc::new(tokio::sync::Semaphore::new(2)),
        })
    }
    fn post(path: &str, origin: &str, host: &str, data: serde_json::Value) -> Request<Body> {
        Request::builder()
            .method("POST")
            .uri(path)
            .header("host", host)
            .header("origin", origin)
            .header("content-type", "application/json")
            .body(Body::from(serde_json::to_vec(&data).unwrap()))
            .unwrap()
    }
    #[test]
    fn canonical_origin_and_ipv6_authority() {
        let a = app("https://admin.example.org/");
        assert_eq!(a.config.public_origin, "https://admin.example.org");
        assert_eq!(a.host, "admin.example.org");
        let a = app("http://[::1]:8081/");
        assert_eq!(a.host, "[::1]:8081");
        assert!(!a.secure_cookie);
        let mut config = a.config.clone();
        config.public_origin = "https://user:pass@admin.example.org".into();
        assert!(normalize_origin(&mut config).is_err());
        config.public_origin = "http://admin.example.org".into();
        assert!(normalize_origin(&mut config).is_err());
    }
    #[tokio::test]
    async fn login_cookie_csrf_and_logout_gate_agent_access() {
        let app = app("https://admin.example.org/");
        let service = router(app.clone());
        let response = service
            .clone()
            .oneshot(post(
                "/api/login",
                "https://evil.example",
                "admin.example.org",
                serde_json::json!({"username":"operator","password":"synthetic-test-password"}),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), 403);
        let response = service
            .clone()
            .oneshot(post(
                "/api/login",
                "https://admin.example.org",
                "evil.example",
                serde_json::json!({"username":"operator","password":"synthetic-test-password"}),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), 400);
        let response = service
            .clone()
            .oneshot(post(
                "/api/login",
                "https://admin.example.org",
                "admin.example.org",
                serde_json::json!({"username":"operator","password":"synthetic-test-password"}),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), 200);
        let cookie = response.headers()[header::SET_COOKIE]
            .to_str()
            .unwrap()
            .to_owned();
        for flag in ["HttpOnly", "SameSite=Strict", "Secure"] {
            assert!(cookie.contains(flag));
        }
        assert_eq!(response.headers()[header::CACHE_CONTROL], "no-store");
        assert!(response.headers().contains_key("content-security-policy"));
        let body = axum::body::to_bytes(response.into_body(), 4096)
            .await
            .unwrap();
        let data: serde_json::Value = serde_json::from_slice(&body).unwrap();
        let csrf = data["csrf"].as_str().unwrap();
        let command = serde_json::json!({"request_id":"fixture","expected_revision":null,"command":{"op":"info"}});
        let mut req = post(
            "/api/command",
            "https://admin.example.org",
            "admin.example.org",
            command.clone(),
        );
        req.headers_mut()
            .insert(header::COOKIE, cookie.parse().unwrap());
        let response = service.clone().oneshot(req).await.unwrap();
        assert_eq!(response.status(), 403);
        let mut req = post(
            "/api/command",
            "https://admin.example.org",
            "admin.example.org",
            command.clone(),
        );
        req.headers_mut()
            .insert(header::COOKIE, cookie.parse().unwrap());
        req.headers_mut()
            .insert("x-csrf-token", csrf.parse().unwrap());
        let response = service.clone().oneshot(req).await.unwrap();
        assert_eq!(
            response.status(),
            503,
            "authenticated request must reach the absent fixture agent"
        );
        let mut req = post(
            "/api/logout",
            "https://admin.example.org",
            "admin.example.org",
            serde_json::json!({}),
        );
        req.headers_mut()
            .insert(header::COOKIE, cookie.parse().unwrap());
        req.headers_mut()
            .insert("x-csrf-token", csrf.parse().unwrap());
        assert_eq!(service.clone().oneshot(req).await.unwrap().status(), 204);
        assert!(app.sessions.lock().unwrap().is_empty());
        let mut req = post(
            "/api/command",
            "https://admin.example.org",
            "admin.example.org",
            command,
        );
        req.headers_mut()
            .insert(header::COOKIE, cookie.parse().unwrap());
        req.headers_mut()
            .insert("x-csrf-token", csrf.parse().unwrap());
        assert_eq!(service.oneshot(req).await.unwrap().status(), 401);
    }
    #[tokio::test]
    async fn rejects_unknown_fields_and_bounds_login_attempts() {
        let app = app("http://localhost:8081");
        let service = router(app.clone());
        let response = service
            .clone()
            .oneshot(post(
                "/api/login",
                "http://localhost:8081",
                "localhost:8081",
                serde_json::json!({"username":"x","password":"x","shell":"x"}),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), 422);
        let response = service
            .clone()
            .oneshot(post(
                "/api/login",
                "http://localhost:8081",
                "localhost:8081",
                serde_json::json!({"username":"x","password":"x"}),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), 401);
        // Seed the recent-attempt window rather than spending a minute on Argon2
        // and allowing the window to expire on a slow development host.
        *app.attempts.lock().unwrap() = (0..12).map(|_| Instant::now()).collect();
        let response = service
            .oneshot(post(
                "/api/login",
                "http://localhost:8081",
                "localhost:8081",
                serde_json::json!({"username":"x","password":"x"}),
            ))
            .await
            .unwrap();
        assert_eq!(response.status(), 429);
    }
}
