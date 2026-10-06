#!/usr/bin/env python3
"""Actual package upgrade/rollback/recovery ONLY on a fresh GitHub-hosted Ubuntu VM."""
import hashlib
import hmac
import json
import os
import pwd
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from pilot_transport import H2Probe, basic, https_through_official_cli

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path("/etc/solartt")
DATA = Path("/var/lib/solartt")
PANEL_DATA = Path("/var/lib/solartt-panel")
SERVICES = ("solartt-agent.service", "solartt-panel.service")
SENTINEL = "solartt-pilot-sentinel.service"
STATE_CODE = """import json,sqlite3,sys
from pathlib import Path
db=sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=ro',uri=True)
schema=db.execute('SELECT version FROM schema_version').fetchone()[0]
doc=json.loads(db.execute('SELECT data FROM document WHERE id=1').fetchone()[0])
ledger=db.execute('SELECT user_id,period_id,charged,confirmed FROM ledger ORDER BY user_id,period_id').fetchall()
print(json.dumps({'schema':schema,'revision':doc['revision'],'users':len(doc['users']),
                 'charged':sum(row[2] for row in ledger),'confirmed':sum(row[3] for row in ledger)}))
"""


def run(*arguments, input=None, success=True):
    result = subprocess.run(arguments, input=input, capture_output=True)
    # Never print command stdout/stderr: profile data and configuration stay private.
    if success and result.returncode:
        raise RuntimeError("Pilot command failed: " + Path(arguments[0]).name)
    if not success and result.returncode == 0:
        raise AssertionError("An unsafe pilot operation unexpectedly succeeded")
    return result


def require_disposable():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_OS") != "Linux"
            or os.environ.get("SOLARTT_PILOT_DISPOSABLE") != "1"
            or os.geteuid() == 0 or not str(ROOT).startswith("/home/runner/work/")):
        raise SystemExit("Pilot installation requires the explicit disposable GitHub-hosted runner")
    release = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
    if release.get("ID", "").strip('"') != "ubuntu" or release.get("VERSION_ID", "").strip('"') != "24.04":
        raise SystemExit("Pilot requires Ubuntu 24.04")
    for path in (CONFIG, DATA, PANEL_DATA):
        if path.exists():
            raise SystemExit("Pilot requires a fresh VM without SolarTT data/configuration")
    if subprocess.run(["dpkg-query", "-W", "solartt-ui"], capture_output=True).returncode == 0:
        raise SystemExit("Pilot requires an uninstalled SolarTT package")


class Pilot:
    def __init__(self):
        self.private = ROOT / ".dev/pilot"
        self.private.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.cookie = ""
        self.csrf = ""
        self.revision = 0
        self.password = "synthetic-pilot-control-password"
        self.database = DATA / "policy.sqlite"
        self.agent_text = ""
        self.probes = []
        self.report = {"environment": "fresh GitHub-hosted Ubuntu 24.04 VM", "checks": []}

    def record(self, name):
        self.report["checks"].append(name)
        print("Pilot verified:", name, flush=True)

    def put(self, name, text):
        temporary = self.private / name
        temporary.write_text(text)
        run("sudo", "install", "-o", "root", "-g", "solartt-control", "-m", "0640",
            str(temporary), str(CONFIG / name))

    def configure(self):
        panel_uid = pwd.getpwnam("solartt-panel").pw_uid
        baseline = ROOT / ".dev/pilot-baseline"
        self.agent_text = (baseline / "examples/agent.toml").read_text().replace(
            "allowed_uids = [1001]", f"allowed_uids = [{panel_uid}]")
        self.put("agent.toml", self.agent_text)
        endpoint = (baseline / "examples/endpoint.toml").read_text().replace(
            ":9443", ":19443").replace(":9080", ":19080").replace(":1987", ":11987")
        self.put("endpoint.toml", endpoint)
        self.put("hosts.toml", (baseline / "examples/hosts.toml").read_text())
        panel = (baseline / "examples/panel.toml").read_text().replace(
            "127.0.0.1:8081", "127.0.0.1:18081").replace("https://admin.example.org", "http://127.0.0.1:18081")
        self.put("panel.toml", panel)
        run("sudo", "-u", "solartt-agent", "solartt-admin", "init-key", str(DATA / "encryption.key"))
        run("sudo", "-u", "solartt-panel", "solartt-panel", "--init-admin",
            str(PANEL_DATA / "admin.hash"), input=self.password.encode())
        self.cert = self.private / "certificate.pem"
        self.tls_key = self.private / "tls.key"
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=media.example.org", "-addext", "subjectAltName=DNS:media.example.org",
            "-keyout", str(self.tls_key), "-out", str(self.cert))
        for path, target in ((self.cert, "fullchain.pem"), (self.tls_key, "private.key")):
            run("sudo", "install", "-o", "root", "-g", "solartt-agent", "-m", "0640",
                str(path), str(CONFIG / "tls" / target))

    def select_database(self, path):
        self.database = path
        self.put("agent.toml", self.agent_text.replace(
            'database = "/var/lib/solartt/policy.sqlite"', "database = " + json.dumps(str(path))))

    def api(self, path, body):
        request = urllib.request.Request("http://127.0.0.1:18081" + path,
            data=json.dumps(body).encode(), headers={
                "Content-Type": "application/json", "Origin": "http://127.0.0.1:18081",
                "Cookie": self.cookie, "X-CSRF-Token": self.csrf})
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.headers.get("Set-Cookie"):
                self.cookie = response.headers["Set-Cookie"].split(";", 1)[0]
            return json.load(response)

    def command(self, command):
        result = self.api("/api/command", {"request_id": f"pilot-{time.time_ns()}",
                          "expected_revision": self.revision, "command": command})
        self.revision = result["desired_revision"]
        if result["result"]["kind"] == "error":
            raise RuntimeError("Pilot control command failed")
        return result["result"]

    def start(self, version):
        run("sudo", "systemctl", "start", *SERVICES)
        deadline = time.monotonic() + 15
        self.cookie = self.csrf = ""
        while True:
            try:
                self.csrf = self.api("/api/login", {"username": "admin", "password": self.password})["csrf"]
                break
            except (urllib.error.URLError, OSError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Pilot panel did not start")
                time.sleep(0.2)
        while True:
            try:
                info = self.command({"op": "info"})["info"]
                assert info["version"] == version
                break
            except urllib.error.HTTPError as error:
                if error.code != 503 or time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        assert run("solartt-agent", "--version").stdout.decode().split()[2] == version
        assert run("solartt-panel", "--version").stdout.decode().split()[2] == version
        self.unchanged_sentinel()

    def stop(self):
        for probe in self.probes:
            probe.close()
        self.probes.clear()
        run("sudo", "systemctl", "stop", *SERVICES)
        self.unchanged_sentinel()

    def state(self, database=None):
        return json.loads(run("sudo", "python3", "-c", STATE_CODE, str(database or self.database)).stdout)

    def digest(self, path):
        return run("sudo", "sha256sum", str(path)).stdout.split()[0]

    def installed(self, version):
        assert run("dpkg-query", "-W", "-f=" + "$" + "{Version}", "solartt-ui").stdout.decode() == version
        for service in SERVICES:
            assert run("systemctl", "is-active", service, success=False).returncode != 0

    def unchanged_sentinel(self):
        assert run("systemctl", "show", SENTINEL, "-p", "MainPID", "--value").stdout.strip() == self.sentinel_pid
        assert int(self.sentinel_pid) > 0
        assert run("systemctl", "show", "ssh.service", "-p", "MainPID", "--value").stdout.strip() == self.ssh_pid

    def profile(self, credential):
        return tomllib.loads(self.command({"op": "export_profile", "credential_id": credential})["toml"])

    def same_profile(self, first, second):
        assert hmac.compare_digest(first["username"], second["username"])
        assert hmac.compare_digest(first["password"], second["password"])
        assert first["hostname"] == second["hostname"]
        assert not second["skip_verification"] and not second["has_ipv6"]

    def authenticate(self, profile, dns=False):
        probe = H2Probe(self.cert)
        self.probes.append(probe)
        probe.check(basic(profile))
        if dns:
            probe.dns(basic(profile))
        return probe

    def traffic(self, profile):
        self.authenticate(profile, dns=True)
        fields = dict(profile, addresses=["127.0.0.1:19443"], certificate=self.cert.read_text())
        configuration = self.private / "official-client.toml"
        configuration.write_text('loglevel = "error"\nvpn_mode = "general"\nkillswitch_enabled = false\n'
            'post_quantum_group_enabled = false\nexclusions_preresolve_enabled = false\n[endpoint]\n'
            + "\n".join(f"{name} = {json.dumps(value)}" for name, value in fields.items())
            + '\n[listener.socks]\naddress = "127.0.0.1:11081"\n')
        configuration.chmod(0o600)
        https_through_official_cli(ROOT / ".dev/official-client/trusttunnel_client", configuration)
        configuration.unlink()

    def snapshot(self, path):
        run("sudo", "-u", "solartt-agent", "solartt-admin", "backup", str(self.database), str(path))

    def main(self):
        baseline_pin = json.loads((ROOT / "upstream/pilot-baseline-pin.json").read_text())
        old = next((ROOT / ".dev/pilot-baseline/dist").glob("*.deb"))
        new = next((ROOT / "dist/current").glob("*.deb"))
        assert json.loads((ROOT / ".dev/pilot-baseline/dist/build.json").read_text())["version"] == baseline_pin["version"]
        assert json.loads((ROOT / "dist/current/build.json").read_text())["version"] == "0.1.0-alpha.2"
        for folder in (ROOT / "dist/current", ROOT / ".dev/pilot-baseline/dist"):
            for line in (folder / "SHA256SUMS").read_text().splitlines():
                expected, name = line.split("  ", 1)
                assert Path(name).name == name
                assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected
        sentinel_file = self.private / "sentinel.service"
        sentinel_file.write_text("[Unit]\nDescription=Unrelated disposable pilot sentinel\n[Service]\n"
                                 "ExecStart=/usr/bin/sleep infinity\nUser=nobody\nNoNewPrivileges=true\n")
        run("sudo", "install", "-o", "root", "-g", "root", "-m", "0644", str(sentinel_file),
            "/etc/systemd/system/" + SENTINEL)
        run("sudo", "systemctl", "daemon-reload")
        run("sudo", "systemctl", "start", SENTINEL)
        self.sentinel_pid = run("systemctl", "show", SENTINEL, "-p", "MainPID", "--value").stdout.strip()
        self.ssh_pid = run("systemctl", "show", "ssh.service", "-p", "MainPID", "--value").stdout.strip()
        run("sudo", "dpkg", "-i", str(old))
        self.installed("0.1.0~alpha1")
        self.configure()
        identities = [(pwd.getpwnam(name).pw_uid, pwd.getpwnam(name).pw_gid)
                      for name in ("solartt-agent", "solartt-panel")]
        key_digest = self.digest(DATA / "encryption.key")
        admin_digest = self.digest(PANEL_DATA / "admin.hash")
        config_digest = self.digest(CONFIG / "agent.toml")
        self.start("0.1.0-alpha.1")
        user = self.command({"op": "create_user", "label": "Synthetic upgrade pilot",
                             "policy": {"limit_bytes": 2000000, "expires_at": None, "reset_monthly": False}})["resource_id"]
        credential = self.command({"op": "create_credential", "user_id": user, "label": "Pilot device"})["resource_id"]
        first = self.profile(credential)
        self.traffic(first)
        self.stop()
        before = self.state()
        assert before["schema"] == 1 and before["confirmed"] > 0 and before["charged"] == before["confirmed"]
        snapshot1 = DATA / "snapshot-schema1.sqlite"
        self.snapshot(snapshot1)
        snapshot1_digest = self.digest(snapshot1)
        self.record("fresh_alpha1_install_and_real_tcp_udp_payload")

        run("sudo", "dpkg", "-i", str(new))
        self.installed("0.1.0~alpha2")
        assert identities == [(pwd.getpwnam(name).pw_uid, pwd.getpwnam(name).pw_gid)
                              for name in ("solartt-agent", "solartt-panel")]
        assert key_digest == self.digest(DATA / "encryption.key")
        assert admin_digest == self.digest(PANEL_DATA / "admin.hash")
        assert config_digest == self.digest(CONFIG / "agent.toml")
        run("sudo", "-u", "solartt-agent", "solartt-admin", "check", str(snapshot1),
            str(DATA / "encryption.key"), "UTC")
        assert self.state(snapshot1)["schema"] == 1 and self.digest(snapshot1) == snapshot1_digest
        self.start("0.1.0-alpha.2")
        after = self.state()
        assert after["schema"] == 2 and {k:after[k] for k in before if k != "schema"} == {
            k:before[k] for k in before if k != "schema"}
        self.same_profile(first, self.profile(credential))
        self.authenticate(first)
        live_candidate = DATA / "must-not-rollback-live.sqlite"
        run("sudo", "-u", "solartt-agent", "solartt-admin", "rollback", str(snapshot1),
            str(self.database), str(DATA / "encryption.key"), "UTC", str(live_candidate), success=False)
        run("sudo", "test", "!", "-e", str(live_candidate))
        self.stop()
        self.record("actual_alpha1_to_alpha2_migration_and_identity_preservation")

        rollback = DATA / "rollback-schema1.sqlite"
        run("sudo", "-u", "solartt-agent", "solartt-admin", "rollback", str(snapshot1),
            str(self.database), str(DATA / "encryption.key"), "UTC", str(rollback))
        assert self.state(rollback)["schema"] == 1
        retained_v2 = self.database
        retained_digest = self.digest(retained_v2)
        run("sudo", "dpkg", "-i", str(old))
        self.installed("0.1.0~alpha1")
        run("sudo", "-u", "solartt-agent", "solartt-admin", "check", str(retained_v2),
            str(DATA / "encryption.key"), "UTC", success=False)
        assert self.digest(retained_v2) == retained_digest
        self.select_database(rollback)
        self.start("0.1.0-alpha.1")
        self.same_profile(first, self.profile(credential))
        self.authenticate(first)
        assert self.state()["confirmed"] == before["confirmed"]
        self.stop()
        self.record("old_binary_schema2_refusal_and_compatible_snapshot_rollback")

        run("sudo", "dpkg", "-i", str(new))
        self.installed("0.1.0~alpha2")
        self.start("0.1.0-alpha.2")
        self.same_profile(first, self.profile(credential))
        self.traffic(first)
        self.stop()
        used = self.state()
        assert used["schema"] == 2 and used["confirmed"] > before["confirmed"]
        unsafe = DATA / "must-not-erase-new-spend.sqlite"
        run("sudo", "-u", "solartt-agent", "solartt-admin", "rollback", str(snapshot1),
            str(self.database), str(DATA / "encryption.key"), "UTC", str(unsafe), success=False)
        run("sudo", "test", "!", "-e", str(unsafe))
        self.record("unsafe_rollback_after_new_payload_is_refused")

        snapshot2 = DATA / "snapshot-schema2.sqlite"
        self.snapshot(snapshot2)
        wrong_key = DATA / "wrong.key"
        run("sudo", "-u", "solartt-agent", "solartt-admin", "init-key", str(wrong_key))
        bad_destination = DATA / "must-not-publish.sqlite"
        run("sudo", "-u", "solartt-agent", "solartt-admin", "restore", str(snapshot2),
            str(wrong_key), str(bad_destination), success=False)
        run("sudo", "test", "!", "-e", str(bad_destination))
        corrupted = DATA / "corrupted.sqlite"
        run("sudo", "install", "-o", "solartt-agent", "-g", "solartt-control", "-m", "0600",
            str(snapshot2), str(corrupted))
        run("sudo", "python3", "-c", "import sys; f=open(sys.argv[1],'r+b'); f.write(b'not-a-database!!'); f.close()", str(corrupted))
        run("sudo", "-u", "solartt-agent", "solartt-admin", "restore", str(corrupted),
            str(DATA / "encryption.key"), str(bad_destination), success=False)
        run("sudo", "test", "!", "-e", str(bad_destination))
        restored = DATA / "recovered-schema2.sqlite"
        run("sudo", "-u", "solartt-agent", "solartt-admin", "restore", str(snapshot2),
            str(DATA / "encryption.key"), str(restored))
        restored_digest = self.digest(restored)
        run("sudo", "-u", "solartt-agent", "solartt-admin", "restore", str(snapshot2),
            str(DATA / "encryption.key"), str(restored), success=False)
        assert restored_digest == self.digest(restored)
        self.select_database(restored)
        self.start("0.1.0-alpha.2")
        self.same_profile(first, self.profile(credential))
        recovered = self.state()
        assert recovered["charged"] == used["charged"] and recovered["confirmed"] == used["confirmed"]
        self.traffic(first)
        self.stop()
        final = self.state()
        assert final["confirmed"] > used["confirmed"]
        assert key_digest == self.digest(DATA / "encryption.key")
        assert admin_digest == self.digest(PANEL_DATA / "admin.hash")
        self.record("schema2_restore_wrong_key_corruption_overwrite_refusal_and_live_payload")

        run("sudo", "dpkg", "-r", "solartt-ui")
        run("sudo", "test", "-f", str(restored))
        assert key_digest == self.digest(DATA / "encryption.key")
        assert admin_digest == self.digest(PANEL_DATA / "admin.hash")
        self.unchanged_sentinel()
        self.record("package_removal_retains_data_and_unrelated_service")
        self.report.update({"baseline_commit": baseline_pin["commit"], "baseline_version": "0.1.0-alpha.1",
                            "current_version": "0.1.0-alpha.2", "schema_before": 1, "schema_after": 2,
                            "baseline_confirmed_payload": before["confirmed"],
                            "before_restore_confirmed_payload": used["confirmed"],
                            "final_confirmed_payload": final["confirmed"],
                            "sentinel_pid_preserved": True, "ssh_pid_preserved": True,
                            "scope": "disposable VM; not Android, production ACME, capacity or complete host recovery"})
        (ROOT / "dist/pilot-report.json").write_text(json.dumps(self.report, indent=2) + "\n")

    def close(self):
        for probe in self.probes:
            probe.close()
        subprocess.run(["sudo", "systemctl", "stop", *SERVICES, SENTINEL], capture_output=True)
        for path in (self.private / "official-client.toml", self.private / "tls.key"):
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    require_disposable()
    pilot = Pilot()
    try:
        pilot.main()
    finally:
        pilot.close()

