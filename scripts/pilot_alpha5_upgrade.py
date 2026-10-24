#!/usr/bin/env python3
"""Published alpha.5/alpha.6/stable -> candidate on a disposable GitHub Ubuntu VM."""
import argparse
import hashlib
import json
import pwd
import subprocess

from pilot_upgrade import (CONFIG, CURRENT_DEB_VERSION, CURRENT_VERSION, DATA, PANEL_DATA,
                           ROOT, SENTINEL, Pilot, require_disposable, run)
from prepare_alpha5_baseline import verify
from publish_alpha import checked_manifest


# Compare policy/credentials and every nonzero per-user quota ledger, without
# printing their contents. Exclude export audit/receipts, which legitimately grow.
FINGERPRINT = """import hashlib,json,sqlite3,sys
from pathlib import Path
db=sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=ro',uri=True)
doc=json.loads(db.execute('SELECT data FROM document WHERE id=1').fetchone()[0])
ledger=db.execute('SELECT user_id,period_id,charged,confirmed FROM ledger WHERE charged<>0 OR confirmed<>0 ORDER BY user_id,period_id').fetchall()
print(hashlib.sha256(json.dumps([doc,ledger],sort_keys=True,separators=(',',':')).encode()).hexdigest())
"""


class Alpha5Pilot(Pilot):
    def __init__(self, baseline="alpha5"):
        if baseline not in {"alpha5", "alpha6", "stable"}:
            raise ValueError("Unknown published baseline")
        super().__init__()
        self.baseline_id = baseline

    def fingerprint(self, database=None):
        return run("sudo", "python3", "-c", FINGERPRINT, str(database or self.database)).stdout.strip()

    def main(self):
        baseline_dir = ROOT / f".dev/{self.baseline_id}-baseline"
        self.baseline = baseline_dir / "root/usr/share/doc/solartt-ui"
        pin = json.loads((ROOT / f"upstream/upgrade-{self.baseline_id}-pin.json").read_text())
        old_deb_version = pin["version"].replace("-alpha.", "~alpha")
        old = verify(baseline_dir, pin)
        candidate = ROOT / "dist/current"
        manifest = checked_manifest(candidate)
        metadata = json.loads((candidate / "build.json").read_text())
        source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        assert metadata["version"] == CURRENT_VERSION and metadata["source_commit"] == source
        packages = list(candidate.glob("*.deb"))
        assert len(packages) == 1
        new = packages[0]
        assert new.name in manifest and "build.json" in manifest
        sentinel = self.private / "sentinel.service"
        sentinel.write_text("[Unit]\nDescription=Unrelated alpha5 pilot sentinel\n[Service]\n"
                            "ExecStart=/usr/bin/sleep infinity\nUser=nobody\nNoNewPrivileges=true\n")
        run("sudo", "install", "-o", "root", "-g", "root", "-m", "0644", str(sentinel),
            "/etc/systemd/system/" + SENTINEL)
        run("sudo", "systemctl", "daemon-reload")
        run("sudo", "systemctl", "start", SENTINEL)
        self.sentinel_pid = run("systemctl", "show", SENTINEL, "-p", "MainPID", "--value").stdout.strip()
        self.ssh_pid = run("systemctl", "show", "ssh.service", "-p", "MainPID", "--value").stdout.strip()
        run("sudo", "dpkg", "-i", str(old))
        self.installed(old_deb_version)
        self.configure()
        self.start(pin["version"])
        credentials = []
        profiles = []
        for label in ("Synthetic alpha5 A", "Synthetic alpha5 B"):
            user = self.command({"op": "create_user", "label": label, "policy": {
                "limit_bytes": 2000000, "expires_at": None, "reset_monthly": False,
                "device_limit": 2}})["resource_id"]
            credential = self.command({"op": "create_credential", "user_id": user,
                                       "label": "Temporary acceptance device"})["resource_id"]
            credentials.append(credential)
            profiles.append(self.profile(credential))
            self.traffic(profiles[-1])
        self.stop()
        before = self.state()
        assert before["schema"] == 2 and before["users"] == 2
        assert before["confirmed"] > 0 and before["charged"] == before["confirmed"]
        identity = self.fingerprint()
        identities = [(pwd.getpwnam(name).pw_uid, pwd.getpwnam(name).pw_gid)
                      for name in ("solartt-agent", "solartt-panel")]
        retained = [DATA / "encryption.key", PANEL_DATA / "admin.hash"] + [
            CONFIG / name for name in ("agent.toml", "panel.toml", "endpoint.toml", "hosts.toml")]
        digests = [self.digest(path) for path in retained]
        snapshot = DATA / "alpha5-before-upgrade.sqlite"
        self.snapshot(snapshot)
        snapshot_digest = self.digest(snapshot)
        self.record("published_alpha5_install_two_users_schema2_and_real_tcp_udp_payload")

        run("sudo", "dpkg", "-i", str(new))
        self.installed(CURRENT_DEB_VERSION)
        assert identities == [(pwd.getpwnam(name).pw_uid, pwd.getpwnam(name).pw_gid)
                              for name in ("solartt-agent", "solartt-panel")]
        assert digests == [self.digest(path) for path in retained]
        self.start(CURRENT_VERSION)
        assert self.state() == before and self.fingerprint() == identity
        for credential, profile in zip(credentials, profiles):
            self.same_profile(profile, self.profile(credential))
            self.authenticate(profile)
        live = DATA / "must-not-rollback-live.sqlite"
        run("sudo", "-u", "solartt-agent", "solartt-admin", "rollback", str(snapshot),
            str(self.database), str(DATA / "encryption.key"), "UTC", str(live), success=False)
        run("sudo", "test", "!", "-e", str(live))
        self.stop()
        assert self.digest(snapshot) == snapshot_digest
        self.record("alpha5_to_candidate_preserves_per_user_policy_profiles_quotas_keys_configs_and_uids")

        # Validate the unchanged snapshot against the actual old binary. Future
        # candidates need not support downgrading their newly changed database.
        rollback = DATA / "alpha5-rollback.sqlite"
        run("sudo", "-u", "solartt-agent", "solartt-admin", "rollback", str(snapshot),
            str(self.database), str(DATA / "encryption.key"), "UTC", str(rollback))
        assert self.fingerprint(rollback) == identity
        candidate_db = self.database
        candidate_digest = self.digest(candidate_db)
        run("sudo", "dpkg", "-i", str(old))
        self.installed(old_deb_version)
        self.select_database(rollback)
        self.start(pin["version"])
        for credential, profile in zip(credentials, profiles):
            self.same_profile(profile, self.profile(credential))
            self.authenticate(profile)
        assert self.fingerprint() == identity
        self.stop()
        assert self.digest(candidate_db) == candidate_digest
        self.record("stopped_snapshot_rollback_to_actual_published_alpha5_without_lost_spend")

        run("sudo", "dpkg", "-i", str(new))
        self.installed(CURRENT_DEB_VERSION)
        self.start(CURRENT_VERSION)
        for profile in profiles:
            self.traffic(profile)
        self.stop()
        used = self.state()
        assert used["confirmed"] > before["confirmed"]
        unsafe = DATA / "must-not-erase-alpha5-new-spend.sqlite"
        run("sudo", "-u", "solartt-agent", "solartt-admin", "rollback", str(snapshot),
            str(self.database), str(DATA / "encryption.key"), "UTC", str(unsafe), success=False)
        run("sudo", "test", "!", "-e", str(unsafe))
        self.record("candidate_new_payload_prevents_stale_alpha5_snapshot_rollback")

        current_snapshot = DATA / "candidate-snapshot.sqlite"
        self.snapshot(current_snapshot)
        restored = DATA / "candidate-restored.sqlite"
        used_identity = self.fingerprint()
        run("sudo", "-u", "solartt-agent", "solartt-admin", "restore", str(current_snapshot),
            str(DATA / "encryption.key"), str(restored))
        self.select_database(restored)
        self.start(CURRENT_VERSION)
        assert self.state() == used and self.fingerprint() == used_identity
        for credential, profile in zip(credentials, profiles):
            self.same_profile(profile, self.profile(credential))
            self.traffic(profile)
        self.stop()
        assert self.state()["confirmed"] > used["confirmed"]
        self.record("candidate_restore_preserves_both_profiles_and_durable_spend_then_forwards_payload")
        run("sudo", "dpkg", "-r", "solartt-ui")
        run("sudo", "test", "-f", str(restored))
        assert digests[:2] == [self.digest(path) for path in retained[:2]]
        self.unchanged_sentinel()
        self.record("removal_retains_data_keys_and_unrelated_services")
        self.report.update({"status": "PASS", "baseline_version": pin["version"],
            "baseline_commit": pin["commit"], "baseline_package_sha256": hashlib.sha256(old.read_bytes()).hexdigest(),
            "candidate_version": CURRENT_VERSION, "candidate_commit": source,
            "candidate_package_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
            "schema_before": before["schema"], "schema_after": used["schema"],
            "baseline_confirmed_payload": before["confirmed"], "candidate_confirmed_payload": used["confirmed"],
            "scope": "disposable VM package upgrade/recovery; not human, Android, real-network or production acceptance"})
        self.report["checks"] = [name.replace("alpha5", self.baseline_id) for name in self.report["checks"]]
        (ROOT / f"dist/{self.baseline_id}-upgrade-report.json").write_text(json.dumps(self.report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", choices=["alpha5", "alpha6", "stable"], default="alpha5")
    args = parser.parse_args()
    require_disposable()
    pilot = Alpha5Pilot(args.baseline)
    try:
        pilot.main()
    finally:
        pilot.close()
