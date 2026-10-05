#!/usr/bin/env python3
"""Private fixture processes, never installed proxies or production configuration.

Used only by package_smoke.py on a disposable runner. The one-second FIN clock
keeps the regression bounded; the shipped integration example specifies 30s.
"""
import csv
import io
import os
import socket
import socketserver
import ssl
import struct
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIN_SECONDS = 1


def stop(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def proxy_header():
    # Synthetic IPv4 source and destination; no production addressing or credentials.
    return (b"\r\n\r\n\0\r\nQUIT\n" + bytes([0x21, 0x11]) + struct.pack("!H", 12)
            + socket.inet_aton("192.0.2.99") + socket.inet_aton("127.0.0.1")
            + struct.pack("!HH", 53000, 19445))


class HoldingServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, direction):
        self.direction = direction
        self.done = threading.Event()

        class Handler(socketserver.BaseRequestHandler):
            def handle(handler):
                connection = handler.request
                connection.settimeout(0.2)
                first = True
                while not self.done.is_set():
                    try:
                        data = connection.recv(65536)
                        if first and data and self.direction == "server":
                            connection.shutdown(socket.SHUT_WR)
                        first = False
                        if not data:
                            # Deliberately leave the other half open after EOF.
                            self.done.wait(15)
                            break
                    except socket.timeout:
                        continue
                    except OSError:
                        break

        super().__init__(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.serve_forever, daemon=True)
        self.worker.start()

    def close(self):
        self.done.set()
        self.shutdown()
        self.server_close()
        self.worker.join(timeout=2)


class ProxyFixture:
    def __init__(self, directory, cert, key):
        self.directory = directory
        self.cert = cert
        self.key = key
        self.processes = []
        self.logs = []
        self.holders = []
        self.clients = []
        self.stats = directory / "haproxy-fixture.sock"

    def process(self, command, name, env=None):
        log = (self.directory / (name + ".log")).open("wb")
        self.logs.append(log)
        process = subprocess.Popen(command, stdout=log, stderr=log, env=env)
        self.processes.append(process)
        return process

    def start(self):
        caddy = ROOT / ".dev/caddy-fixture/caddy"
        configuration = self.directory / "Caddyfile.fixture"
        configuration.write_text(f"""{{\n
    admin off
    persist_config off
    auto_https off
    servers {{
        protocols h1 h2
        listener_wrappers {{
            proxy_protocol {{
                timeout 2s
                allow 127.0.0.1/32
                fallback_policy reject
            }}
            tls
        }}
    }}
}}
https://tg.example.org:19445 {{
    bind 127.0.0.1
    tls {self.cert} {self.key}
    respond "Existing fixture {{http.request.remote.host}}" 200
}}
""")
        environment = dict(os.environ, XDG_DATA_HOME=str(self.directory / "caddy-data"),
                           XDG_CONFIG_HOME=str(self.directory / "caddy-config"))
        subprocess.run([str(caddy), "validate", "--adapter", "caddyfile", "--config", str(configuration)],
                       env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        self.process([str(caddy), "run", "--adapter", "caddyfile", "--config", str(configuration)],
                     "caddy", environment)
        self.holders = [HoldingServer(direction) for direction in ("client", "server")]
        self.launch_proxy(19444, self.stats, fin=True, name="haproxy")

    def launch_proxy(self, port, stats, fin, name):
        fin_lines = "    timeout client-fin 1s\n    timeout server-fin 1s\n" if fin else ""
        configuration = self.directory / (name + ".cfg")
        configuration.write_text(f"""global
    maxconn 32
    stats socket {stats} mode 600 level user
defaults
    mode tcp
    timeout connect 3s
    timeout client 60s
    timeout server 60s
{fin_lines}frontend fixture
    bind 127.0.0.1:{port}
    tcp-request inspect-delay 3s
    tcp-request content accept if {{ req.ssl_hello_type 1 }}
    use_backend tunnel if {{ req.ssl_sni -i media.example.org }}
    use_backend existing if {{ req.ssl_sni -i tg.example.org }}
    use_backend held_client if {{ req.ssl_sni -i fin-client.example.org }}
    use_backend held_server if {{ req.ssl_sni -i fin-server.example.org }}
    tcp-request content reject if !{{ req.ssl_sni -i media.example.org tg.example.org fin-client.example.org fin-server.example.org }}
backend tunnel
    server tunnel 127.0.0.1:19443
backend existing
    server existing 127.0.0.1:19445 send-proxy-v2
backend held_client
    server held 127.0.0.1:{self.holders[0].server_address[1]}
backend held_server
    server held 127.0.0.1:{self.holders[1].server_address[1]}
""")
        subprocess.run(["haproxy", "-c", "-f", str(configuration)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        process = self.process(["haproxy", "-db", "-f", str(configuration)], name)
        deadline = time.monotonic() + 5
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"Fixture {name} exited")
            try:
                self.counts(stats)
                return process
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Fixture {name} did not become ready")
                time.sleep(0.05)

    @staticmethod
    def counts(stats):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(2)
            connection.connect(str(stats))
            connection.sendall(b"show stat\n")
            connection.shutdown(socket.SHUT_WR)
            data = bytearray()
            while chunk := connection.recv(65536):
                data.extend(chunk)
        rows = csv.DictReader(io.StringIO(data.decode().removeprefix("# ")))
        return {row["pxname"]: int(row["scur"]) for row in rows if row["svname"] == "BACKEND"}

    def half_closed(self, port):
        connections = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        for direction in ("client", "server"):
            outgoing = ssl.MemoryBIO()
            tls = context.wrap_bio(ssl.MemoryBIO(), outgoing,
                                   server_hostname=f"fin-{direction}.example.org")
            try:
                tls.do_handshake()
            except ssl.SSLWantReadError:
                pass
            hello = outgoing.read()
            assert hello and hello[0] == 22
            for _ in range(2):
                connection = socket.create_connection(("127.0.0.1", port), timeout=3)
                self.clients.append(connection)
                connections.append(connection)
                connection.sendall(hello)
                if direction == "client":
                    connection.shutdown(socket.SHUT_WR)
                else:
                    assert connection.recv(1) == b"", "Backend did not half-close"
        return connections

    def fin_regression(self, check_control):
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            negative_port = reserve.getsockname()[1]
        negative_stats = self.directory / "haproxy-no-fin.sock"
        negative = self.launch_proxy(negative_port, negative_stats, fin=False, name="haproxy-no-fin")
        negative_clients = self.half_closed(negative_port)
        # Without FIN directives, the exact same workload must persist.
        # The ordinary H2 control is intentionally idle for longer than the FIN clock.
        time.sleep(2 * FIN_SECONDS + 0.25)
        retained = self.counts(negative_stats)
        assert retained["held_client"] == retained["held_server"] == 2, retained
        check_control()
        for connection in negative_clients:
            connection.close()
        stop(negative)

        started = time.monotonic()
        positive_clients = self.half_closed(19444)
        observed = self.counts(self.stats)
        assert observed["held_client"] == observed["held_server"] == 2, observed
        deadline = started + 5
        controls = 0
        while True:
            check_control()
            controls += 1
            counts = self.counts(self.stats)
            if counts["held_client"] == counts["held_server"] == 0:
                break
            if time.monotonic() >= deadline:
                raise AssertionError(f"FIN connections not released: {counts}")
            time.sleep(0.15)
        for connection in positive_clients:
            connection.close()
        elapsed = time.monotonic() - started
        assert elapsed >= 0.5, "Fixture did not actually retain half-closed sessions"
        result = {"fin_timeout_seconds": FIN_SECONDS, "normal_timeout_seconds": 60,
                  "connections_per_direction": 2, "no_fin_retained": 4,
                  "fin_released": 4, "release_seconds": elapsed,
                  "live_h2_control_checks": controls, "idle_h2_control_survived": True}
        print("Both FIN directions released; no-FIN control reproduced retention; H2 survived")
        return result

    def proxy_v2_regression(self):
        context = ssl.create_default_context(cafile=str(self.cert))
        # The source differs from the proxy's backend peer: echo proves PROXY metadata.
        with socket.create_connection(("127.0.0.1", 19444), timeout=3,
                                      source_address=("127.0.0.2", 0)) as raw:
            with context.wrap_socket(raw, server_hostname="tg.example.org") as connection:
                connection.sendall(b"GET / HTTP/1.1\r\nHost: tg.example.org\r\nConnection: close\r\n\r\n")
                data = bytearray()
                while chunk := connection.recv(65536):
                    data.extend(chunk)
                assert data.startswith(b"HTTP/1.1 200") and b"Existing fixture 127.0.0.2" in data
        # An immediate peer outside the allowlist cannot inject PROXY metadata.
        with socket.create_connection(("127.0.0.1", 19445), timeout=3,
                                      source_address=("127.0.0.2", 0)) as raw:
            try:
                raw.sendall(proxy_header())
                with context.wrap_socket(raw, server_hostname="tg.example.org"):
                    raise AssertionError("Untrusted peer injected PROXY metadata")
            except (ssl.SSLError, ConnectionResetError, BrokenPipeError):
                pass
        # A prefixed TLS attempt to TT must fail; valid no-prefix H2 is checked separately.
        with socket.create_connection(("127.0.0.1", 19443), timeout=3) as raw:
            try:
                raw.sendall(proxy_header())
                with context.wrap_socket(raw, server_hostname="media.example.org"):
                    raise AssertionError("TrustTunnel unexpectedly accepted a PROXY header")
            except (ssl.SSLError, ConnectionResetError, BrokenPipeError):
                pass
        print("Caddy PROXY v2 metadata verified; untrusted peer and TT prefix rejected")

    def close(self):
        for connection in self.clients:
            connection.close()
        for process in reversed(self.processes):
            stop(process)
        for holder in self.holders:
            holder.close()
        for log in self.logs:
            log.close()
