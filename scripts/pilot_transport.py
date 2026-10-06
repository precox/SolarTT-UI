"""Private TLS/H2 probes used by the disposable upgrade pilot."""
import base64
import os
import socket
import ssl
import struct
import subprocess
import time
from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import DataReceived, ResponseReceived, StreamEnded


class H2Probe:
    def __init__(self, certificate):
        context = ssl.create_default_context(cafile=str(certificate))
        context.set_alpn_protocols(["h2"])
        self.socket = context.wrap_socket(socket.create_connection(("127.0.0.1", 19443), timeout=4),
                                          server_hostname="media.example.org")
        self.socket.settimeout(4)
        assert self.socket.selected_alpn_protocol() == "h2"
        self.connection = H2Connection(config=H2Configuration(
            client_side=True, header_encoding="utf-8", validate_outbound_headers=False))
        self.connection.initiate_connection()
        self.socket.sendall(self.connection.data_to_send())

    def request(self, authority, basic):
        stream = self.connection.get_next_available_stream_id()
        self.connection.send_headers(stream, [
            (":method", "CONNECT"), (":authority", authority),
            ("proxy-authorization", "Basic " + basic)], end_stream=authority == "_check")
        self.socket.sendall(self.connection.data_to_send())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            data = self.socket.recv(65536)
            if not data:
                raise RuntimeError("Pilot H2 transport closed")
            for event in self.connection.receive_data(data):
                if isinstance(event, ResponseReceived) and event.stream_id == stream:
                    self.socket.sendall(self.connection.data_to_send())
                    return stream, dict(event.headers)[":status"]
            self.socket.sendall(self.connection.data_to_send())
        raise RuntimeError("Pilot H2 response deadline exceeded")

    def check(self, basic):
        assert self.request("_check", basic)[1] == "200", "Saved profile failed authentication"

    def dns(self, basic):
        stream, status = self.request("_udp2", basic)
        assert status == "200"
        query_id = int.from_bytes(os.urandom(2), "big")
        query = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + b"\x07example\x03com\x00" + struct.pack("!HH", 1, 1)
        metadata = (bytes(12) + socket.inet_aton("10.0.0.2") + struct.pack("!H", 53000)
                    + bytes(12) + socket.inet_aton("1.1.1.1") + struct.pack("!H", 53) + b"\0")
        frame = struct.pack("!I", len(metadata) + len(query)) + metadata + query
        self.connection.send_data(stream, frame, end_stream=False)
        self.socket.sendall(self.connection.data_to_send())
        received = bytearray()
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            data = self.socket.recv(65536)
            if not data:
                raise RuntimeError("Pilot DNS stream closed")
            for event in self.connection.receive_data(data):
                if isinstance(event, DataReceived):
                    self.connection.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    if event.stream_id == stream:
                        received.extend(event.data)
                elif isinstance(event, StreamEnded) and event.stream_id == stream:
                    raise RuntimeError("Pilot DNS stream ended before reply")
            self.socket.sendall(self.connection.data_to_send())
            if len(received) >= 4:
                length = int.from_bytes(received[:4], "big")
                if len(received) >= 4 + length:
                    reply = received[40:4+length]
                    assert len(reply) >= 12
                    reply_id, flags, _, answers, _, _ = struct.unpack("!HHHHHH", reply[:12])
                    assert reply_id == query_id and flags & 0x8000 and flags & 0xF == 0 and answers > 0
                    return
        raise RuntimeError("Pilot UDP/DNS reply deadline exceeded")

    def close(self):
        self.socket.close()


def basic(profile):
    return base64.b64encode((profile["username"] + ":" + profile["password"]).encode()).decode()


def https_through_official_cli(executable, configuration):
    process = subprocess.Popen([str(executable), "--config", str(configuration)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                raise RuntimeError("Pilot official CLI exited")
            try:
                with socket.create_connection(("127.0.0.1", 11081), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Pilot official CLI did not start")
                time.sleep(0.1)
        result = subprocess.run(["curl", "--silent", "--show-error", "--fail",
                                 "--socks5", "127.0.0.1:11081", "--connect-timeout", "10",
                                 "--max-time", "20", "--output", "/dev/null", "https://example.com/"],
                                capture_output=True)
        if result.returncode:
            raise RuntimeError("Pilot HTTPS via official CLI failed")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
