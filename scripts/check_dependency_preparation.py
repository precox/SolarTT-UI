#!/usr/bin/env python3
"""Real candidate preparation against a clearly synthetic historical fixture.

Only disposable GitHub runners. No GitHub writes, no release simulation and no
installation. The normal checkout/pin remain unchanged.
"""
import copy
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path

from dependency_policy import index
from maintain_dependencies import ROOT, audit, prepare, require_runner


def main():
    require_runner()
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    real, status = audit(ROOT)
    clean = prepare(ROOT, real, status, base)
    if clean["summary"]["decision"] != "healthy":
        raise RuntimeError("Current checkout must first pass the real security gate")
    print("Real checkout audit: healthy, no proposed changes")
    entries = index("rustls-webpki")
    records = {v: entries[v] for v in ("0.103.15", "0.103.16")}
    with tempfile.TemporaryDirectory(prefix="solartt-dependency-fixture-") as folder:
        root = Path(folder)
        tree = subprocess.check_output(["git", "archive", "HEAD"], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(tree)) as archive:
            archive.extractall(root, filter="data")
        shutil.copytree(ROOT / ".upstream", root / ".upstream")
        lock = (root / "Cargo.lock").read_text()
        package = next(p for p in tomllib.loads(lock)["package"] if p["name"] == "rustls-webpki")
        old_identity = f'name = "rustls-webpki"\nversion = "{package["version"]}"'
        lock = lock.replace(old_identity, 'name = "rustls-webpki"\nversion = "0.103.15"', 1)
        lock = lock.replace(package["checksum"], records["0.103.15"]["cksum"], 1)
        (root / "Cargo.lock").write_text(lock)
        review = json.loads((root / "upstream/license-review.json").read_text())
        approved = next(p for p in review["packages"] if p["name"] == "rustls-webpki")
        approved.update(version="0.103.15", declared_license="ISC", selected_license="ISC",
                        notices_sha256={"LICENSE": "5b698ca13897be3afdb7174256fa1574f8c6892b8bea1a66dd6469d3fe27885a"})
        (root / "upstream/license-review.json").write_text(json.dumps(review, indent=2) + "\n")
        fixture = {"database": real["database"], "vulnerabilities": {"count": 1, "list": [{
            "package": {"name": "rustls-webpki", "version": "0.103.15"},
            "advisory": {"id": "RUSTSEC-2026-0382"},
            "versions": {"patched": [">=0.103.16, <0.104.0-alpha.1", ">=0.104.0-alpha.8"]}}]}}
        candidate = prepare(root, fixture, 1, base, registry=lambda _: records)
        if candidate["summary"]["decision"] != "patch" or candidate["summary"]["target"]["to"] != "0.103.16":
            raise RuntimeError("Historical patch fixture did not produce a verified patch candidate")
        if (root / "Cargo.lock").read_text() != lock:
            raise RuntimeError("Fixture did not restore its original lockfile")
        print("TEST fixture: 0.103.15 -> 0.103.16, real Cargo resolution/metadata, checksum/notices and post-audit PASS")
        review["packages"] = copy.deepcopy(review["packages"])
        next(p for p in review["packages"] if p["name"] == "rustls-webpki")["notices_sha256"]["LICENSE"] = "0" * 64
        (root / "upstream/license-review.json").write_text(json.dumps(review, indent=2) + "\n")
        declined = prepare(root, fixture, 1, base, registry=lambda _: records)
        if declined["summary"]["decision"] != "manual" or len(declined["files"]) != 1:
            raise RuntimeError("Changed notices were not stopped for manual review")
        print("TEST fixture: changed notice -> report-only manual draft; no GitHub writes")


if __name__ == "__main__":
    main()
