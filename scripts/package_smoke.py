#!/usr/bin/env python3
"""Install and exercise packages ONLY on disposable GitHub Actions Ubuntu runners."""
import base64
import hashlib
import http.server
import json
import os
import pwd
import socket
import ssl
import subprocess
import threading
import time
import tomllib
import urllib.request
import urllib.error
from pathlib import Path

from proxy_regression import ProxyFixture

ROOT = Path(__file__).resolve().parents[1]


def run(*args, input=None):
    result = subprocess.run(args, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        # Diagnostics contain command output only; never include stdin or profiles.
        print(result.stderr.decode(errors="replace"), flush=True)
        result.check_returncode()
    return result


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux":
        raise SystemExit("Package smoke test requires a disposable GitHub Actions Linux runner")
    if os.geteuid() == 0:
        raise SystemExit("Run as the runner user; privileged actions use explicit sudo")
    deb = next((ROOT / "dist").glob("*.deb"))
    config = Path("/etc/solartt")
    data = Path("/var/lib/solartt")
    panel_data = Path("/var/lib/solartt-panel")
    services = ("solartt-agent.service", "solartt-panel.service")
    sentinel_pid = run("systemctl", "show", "ssh.service", "-p", "MainPID", "--value").stdout.strip()
    run("sudo", "dpkg", "-i", str(deb))
    panel_uid = pwd.getpwnam("solartt-panel").pw_uid
    temporary = ROOT / ".dev/smoke"
    temporary.mkdir(parents=True, exist_ok=True)
    temporary.chmod(0o700)

    def put(name, text):
        source = temporary / name
        source.write_text(text)
        run("sudo", "install", "-o", "root", "-g", "solartt-control", "-m", "0640", str(source), str(config / name))

    agent = (ROOT / "examples/agent.toml").read_text().replace("allowed_uids = [1001]", f"allowed_uids = [{panel_uid}]")
    put("agent.toml", agent)
    endpoint = "tls_handshake_timeout_secs = 1\n" + (ROOT / "examples/endpoint.toml").read_text().replace(":9443", ":19443").replace(":9080", ":19080").replace(":1987", ":11987")
    put("endpoint.toml", endpoint)
    put("hosts.toml", (ROOT / "examples/hosts.toml").read_text())
    panel = (ROOT / "examples/panel.toml").read_text().replace("127.0.0.1:8081", "127.0.0.1:18081").replace("https://admin.example.org", "http://127.0.0.1:18081")
    put("panel.toml", panel)
    # Passwords are supplied through stdin and never included in command arguments.
    password = "synthetic-package-smoke-password"
    run("sudo", "-u", "solartt-agent", "solartt-admin", "init-key", str(data / "encryption.key"))
    run("sudo", "-u", "solartt-panel", "solartt-panel", "--init-admin", str(panel_data / "admin.hash"), input=password.encode())

    def certificate(serial):
        cert, key = temporary / f"cert-{serial}.pem", temporary / f"key-{serial}.pem"
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-set_serial", str(serial),
            "-subj", "/CN=media.example.org", "-addext", "subjectAltName=DNS:media.example.org,DNS:tg.example.org", "-keyout", str(key), "-out", str(cert))
        for source, name in ((cert, "fullchain.pem"), (key, "private.key")):
            target = config / "tls" / name
            stage = str(target) + ".new"
            run("sudo", "install", "-o", "root", "-g", "solartt-agent", "-m", "0640", str(source), stage)
            run("sudo", "mv", stage, str(target))
        return cert

    cert = certificate(1)
    class Cover(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_GET(self):
            body = b"Isolated cover fixture"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_):
            pass
    cover = http.server.ThreadingHTTPServer(("127.0.0.1", 19080), Cover)
    threading.Thread(target=cover.serve_forever, daemon=True).start()
    proxies = ProxyFixture(temporary, cert, temporary / "key-1.pem")
    official = None
    try:
        proxies.start()
        run("haproxy", "-c", "-f", str(ROOT / "examples/haproxy.cfg"))
        run("sudo", "systemctl", "start", *services)
        deadline = time.monotonic() + 15
        while True:
            try:
                with socket.create_connection(("127.0.0.1", 18081), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Panel failed to start")
                time.sleep(0.1)
        cookie = ""
        csrf = ""
        revision = 0
        def api(path, payload):
            nonlocal cookie, csrf
            request = urllib.request.Request("http://127.0.0.1:18081" + path, data=json.dumps(payload).encode(), headers={
                "Content-Type": "application/json", "Origin": "http://127.0.0.1:18081", "Cookie": cookie, "X-CSRF-Token": csrf})
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.headers.get("Set-Cookie"):
                    cookie = response.headers["Set-Cookie"].split(";", 1)[0]
                return json.load(response)
        csrf = api("/api/login", {"username": "admin", "password": password})["csrf"]
        def command(op):
            nonlocal revision
            result = api("/api/command", {"request_id": f"smoke-{time.time_ns()}", "expected_revision": revision, "command": op})
            revision = result["desired_revision"]
            if result["result"]["kind"] == "error":
                raise RuntimeError("Agent command failed")
            return result["result"]
        # Type=simple starts before the agent has opened its IPC/TLS listeners.
        deadline = time.monotonic() + 15
        while True:
            try:
                assert command({"op": "info"})["info"]["readiness"]
                break
            except urllib.error.HTTPError as error:
                if error.code != 503 or time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        # Filesystem permissions deny unrelated users; peer UID validation also
        # denies a process that can bypass those permissions but is not allowed.
        run("sudo", "-u", "nobody", "python3", "-c", """import errno,socket
s=socket.socket(socket.AF_UNIX)
try:
    s.connect('/run/solartt/control.sock')
except OSError as error:
    assert error.errno == errno.EACCES
else:
    raise AssertionError('Unrelated user accessed control socket')
""")
        run("sudo", "python3", "-c", """import socket
s=socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect('/run/solartt/control.sock')
try:
    s.sendall(b'{"request_id":"uid-probe","expected_revision":null,"command":{"op":"info"}}\\n')
    response=s.recv(4096)
except (ConnectionResetError,BrokenPipeError):
    response=b''
assert not response, 'Unlisted peer UID received control data'
""")
        run("sudo", "-u", "solartt-panel", "python3", "-c", """import os
assert not os.access('/var/lib/solartt/encryption.key',os.R_OK)
assert not os.access('/etc/solartt/tls/private.key',os.R_OK)
""")
        assert not command({"op": "users", "after": None})["users"]
        user = command({"op": "create_user", "label": "Synthetic package fixture", "policy": {"limit_bytes": 100000, "expires_at": None, "reset_monthly": True}})["resource_id"]
        credential = command({"op": "create_credential", "user_id": user, "label": "Fixture"})["resource_id"]
        profile = command({"op": "export_profile", "credential_id": credential})
        client = tomllib.loads(profile["toml"])
        assert not client["skip_verification"] and not client["has_ipv6"]
        assert "<svg" in profile["qr_svg"]
        audit = command({"op": "audit", "before": None})["entries"]
        assert len(audit) == 3
        assert audit[0]["operation"] == "profile_export_prepared"
        assert audit[0]["actor_uid"] == panel_uid and audit[0]["credential_id"] == credential
        assert audit[0]["subject"] == user and audit[0]["request_id"].startswith("smoke-")
        info = command({"op": "info"})["info"]
        assert info["storage"]["schema_version"] == 2
        assert info["storage"]["audit_rows"] == 3 and not info["storage"]["last_write_failed"]
        denied = api("/api/command", {"request_id": "smoke-denied-export", "expected_revision": revision,
            "command": {"op": "export_profile", "credential_id": "00000000-0000-0000-0000-000000000001"}})
        assert denied["result"]["kind"] == "error" and "toml" not in denied["result"]
        audit = command({"op": "audit", "before": None})["entries"]
        assert audit[0]["operation"] == "profile_export_denied" and audit[0]["actor_uid"] == panel_uid
        assert audit[0]["request_id"] == "smoke-denied-export"
        try:
            api("/api/command", {"request_id": "smoke-spoof-uid", "expected_revision": revision,
                "actor_uid": 0, "command": {"op": "info"}})
        except urllib.error.HTTPError as error:
            assert error.code == 422
        else:
            raise AssertionError("Untrusted JSON spoofed the caller UID")

        from h2.connection import H2Connection
        from h2.config import H2Configuration
        from h2.events import ResponseReceived
        class H2Probe:
            def __init__(self, cafile):
                context = ssl.create_default_context(cafile=str(cafile))
                context.set_alpn_protocols(["h2"])
                self.socket = context.wrap_socket(socket.create_connection(("127.0.0.1", 19444), timeout=3), server_hostname="media.example.org")
                self.socket.settimeout(3)
                # Ubuntu's hyper-h2 validator requires :path even for CONNECT.
                # Send the authority-only CONNECT form used by the official client.
                self.h2 = H2Connection(config=H2Configuration(client_side=True, header_encoding="utf-8", validate_outbound_headers=False))
                self.h2.initiate_connection()
                self.socket.sendall(self.h2.data_to_send())
            def check(self, basic):
                stream = self.h2.get_next_available_stream_id()
                self.h2.send_headers(stream, [(":method", "CONNECT"), (":authority", "_check"), ("proxy-authorization", "Basic " + basic)], end_stream=True)
                self.socket.sendall(self.h2.data_to_send())
                while True:
                    data = self.socket.recv(65536)
                    if not data:
                        raise RuntimeError("H2 transport closed unexpectedly")
                    for event in self.h2.receive_data(data):
                        if isinstance(event, ResponseReceived) and event.stream_id == stream:
                            return dict(event.headers)[":status"]
                    self.socket.sendall(self.h2.data_to_send())
            def close(self):
                self.socket.close()
        basic = base64.b64encode((client["username"] + ":" + client["password"]).encode()).decode()
        bad = H2Probe(cert)
        assert bad.check("eDp4") == "404"
        bad.close()
        probe = H2Probe(cert)
        assert probe.check(basic) == "200"
        def check_control():
            assert probe.check(basic) == "200", "FIN regression interrupted H2 control"
        proxy_result = proxies.fin_regression(check_control)
        proxies.proxy_v2_regression()
        proxy_result["caddy_proxy_v2"] = "verified metadata and untrusted-peer rejection"
        proxy_result["trusttunnel_proxy_header"] = "rejected; no-prefix TLS/H2 succeeds"
        (ROOT / "dist/proxy-regression.json").write_text(json.dumps(proxy_result, indent=2) + "\n")
        # The second SNI retains its independent TLS endpoint and certificate.
        existing_context = ssl.create_default_context(cafile=str(cert))
        with existing_context.wrap_socket(socket.create_connection(("127.0.0.1", 19444), timeout=3), server_hostname="tg.example.org") as connection:
            connection.sendall(b"GET / HTTP/1.0\r\nHost: tg.example.org\r\n\r\n")
            assert b"200" in connection.recv(4096).split(b"\r\n", 1)[0]
        pid = run("systemctl", "show", services[0], "-p", "MainPID", "--value").stdout.strip()
        old_cert = hashlib.sha256(probe.socket.getpeercert(binary_form=True)).digest()
        cert = certificate(2)
        run("sudo", "systemctl", "reload", services[0])
        # The signal is asynchronous; poll fresh handshakes for the new certificate.
        deadline = time.monotonic() + 5
        while True:
            try:
                new = H2Probe(cert)
                assert hashlib.sha256(new.socket.getpeercert(binary_form=True)).digest() != old_cert
                assert new.check(basic) == "200"
                new.close()
                break
            except ssl.SSLError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        assert probe.check(basic) == "200", "TLS reload interrupted an existing user"
        assert pid == run("systemctl", "show", services[0], "-p", "MainPID", "--value").stdout.strip()
        context = ssl.create_default_context(cafile=str(cert))
        context.set_alpn_protocols(["http/1.1"])
        with context.wrap_socket(socket.create_connection(("127.0.0.1", 19444), timeout=3), server_hostname="media.example.org") as connection:
            connection.sendall(b"GET / HTTP/1.1\r\nHost: media.example.org\r\nConnection: close\r\n\r\n")
            assert b"200" in connection.recv(4096).split(b"\r\n", 1)[0]
        # Exercise the exported endpoint fields with the pinned official client.
        # SOCKS mode is unprivileged: no TUN, routes, DNS or firewall mutations.
        endpoint_fields = dict(client)
        endpoint_fields["addresses"] = ["127.0.0.1:19444"]
        endpoint_fields["certificate"] = cert.read_text()
        official_config = temporary / "official-client.toml"
        official_config.write_text('loglevel = "error"\nvpn_mode = "general"\nkillswitch_enabled = false\n'
            'post_quantum_group_enabled = false\nexclusions_preresolve_enabled = false\n'
            '[endpoint]\n' + "\n".join(f"{key} = {json.dumps(value)}" for key, value in endpoint_fields.items()) +
            '\n[listener.socks]\naddress = "127.0.0.1:11080"\n')
        official_config.chmod(0o600)
        official = subprocess.Popen([str(ROOT / ".dev/official-client/trusttunnel_client"), "--config", str(official_config)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while True:
            if official.poll() is not None:
                raise RuntimeError("Official CLI exited before opening its SOCKS listener")
            try:
                with socket.create_connection(("127.0.0.1", 11080), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Official CLI SOCKS listener failed to start")
                time.sleep(0.1)
        # A single small public HTTPS request verifies real outbound TCP through
        # the official client, the SNI proxy and the managed packaged endpoint.
        # This check depends on runner DNS/egress and example.com availability.
        run("curl", "--silent", "--show-error", "--fail", "--socks5", "127.0.0.1:11080",
            "--connect-timeout", "10", "--max-time", "20", "--output", "/dev/null", "https://example.com/")
        view = command({"op": "users", "after": None})["users"][0]
        assert view["confirmed_bytes"] > 0 and view["active_sessions"] >= 2
        command({"op": "block_user", "user_id": user, "blocked": True})
        # There may be previously queued H2 control frames before EOF.
        deadline = time.monotonic() + 3
        while probe.socket.recv(65536):
            if time.monotonic() >= deadline:
                raise RuntimeError("Revoked TLS connection remained open")
        probe.close()
        assert command({"op": "users", "after": None})["users"][0]["active_sessions"] == 0
        run("node", str(ROOT / "scripts/browser_smoke.mjs"), input=json.dumps({
            "origin": "http://127.0.0.1:18081", "password": password}).encode())
        print("Browser interaction and secret-clearing checks passed")
        run("sudo", "systemctl", "stop", *services)
        run("sudo", "-u", "solartt-agent", "solartt-admin", "backup", str(data / "policy.sqlite"), str(data / "snapshot.sqlite"))
        run("sudo", "-u", "solartt-agent", "solartt-admin", "restore", str(data / "snapshot.sqlite"), str(data / "encryption.key"), str(data / "restored.sqlite"))
        run("sudo", "-u", "solartt-agent", "solartt-admin", "check", str(data / "restored.sqlite"), str(data / "encryption.key"), "UTC", "/usr/share/doc/solartt-ui/examples/retention.toml")
        key_digest = run("sudo", "sha256sum", str(data / "encryption.key")).stdout
        config_digest = run("sudo", "sha256sum", str(config / "agent.toml")).stdout
        run("sudo", "dpkg", "-i", str(deb))
        assert key_digest == run("sudo", "sha256sum", str(data / "encryption.key")).stdout
        assert config_digest == run("sudo", "sha256sum", str(config / "agent.toml")).stdout
        run("sudo", "dpkg", "-r", "solartt-ui")
        run("sudo", "test", "-f", str(data / "policy.sqlite"))
        assert key_digest == run("sudo", "sha256sum", str(data / "encryption.key")).stdout
        assert sentinel_pid == run("systemctl", "show", "ssh.service", "-p", "MainPID", "--value").stdout.strip()
        print("Package install, API, verified TLS, SNI passthrough, reload, cover, revoke, backup, reinstall and removal checks passed")
    finally:
        subprocess.run(["sudo", "systemctl", "stop", *services], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cover.shutdown()
        proxies.close()
        for process in (official,):
            if process is None:
                continue
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for key in temporary.glob("key-*.pem"):
            key.unlink()
        (temporary / "official-client.toml").unlink(missing_ok=True)

if __name__ == "__main__":
    main()
