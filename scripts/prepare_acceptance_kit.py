#!/usr/bin/env python3
"""Assemble passive, public test inputs only; never configure or deploy a host."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from prepare_alpha5_baseline import verify
from publish_alpha import checked_manifest

ROOT = Path(__file__).resolve().parents[1]


def main():
    pin = json.loads((ROOT / "upstream/upgrade-alpha5-pin.json").read_text())
    baseline = ROOT / ".dev/alpha5-baseline"
    old = verify(baseline, pin)
    candidate = ROOT / "dist/current"
    manifest = checked_manifest(candidate)
    packages = list(candidate.glob("*.deb"))
    if len(packages) != 1 or packages[0].name not in manifest or "build.json" not in manifest:
        raise SystemExit("Expected one checksummed candidate package")
    new = packages[0]
    metadata = json.loads((candidate / "build.json").read_text())
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = json.loads((ROOT / "dist/alpha5-upgrade-report.json").read_text())
    if (metadata["source_commit"] != source or report.get("status") != "PASS"
            or report["candidate_commit"] != source
            or report["candidate_package_sha256"] != hashlib.sha256(new.read_bytes()).hexdigest()):
        raise SystemExit("Acceptance kit requires this candidate's successful alpha.5 upgrade report")
    destination = ROOT / "dist/manual-acceptance-kit"
    destination.mkdir(exist_ok=False)
    # Explicit allowlist: no .dev/pilot state, keys, databases, profiles or logs.
    for label, package, folder in (("baseline", old, baseline), ("candidate", new, candidate)):
        output = destination / label
        output.mkdir()
        shutil.copyfile(package, output / package.name)
        shutil.copyfile(folder / "build.json", output / "build.json")
    for name in ("manual-acceptance.md", "manual-acceptance-record.md", "backup-upgrade.md"):
        shutil.copyfile(ROOT / "docs" / name, destination / name)
    shutil.copyfile(ROOT / "dist/alpha5-upgrade-report.json", destination / "alpha5-upgrade-report.json")
    shutil.copytree(ROOT / "examples", destination / "examples")
    (destination / "identity.json").write_text(json.dumps({
        "baseline": pin, "candidate": metadata,
        "workflow_url": f"https://github.com/precox/SolarTT-UI/actions/runs/{os.environ['GITHUB_RUN_ID']}",
        "state": "PREPARED_ONLY", "human_acceptance": "NOT_PERFORMED",
        "deployment": "NOT_PERFORMED"}, indent=2) + "\n")
    files = sorted(path for path in destination.rglob("*") if path.is_file())
    (destination / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(destination).as_posix()}\n"
        for path in files))
    print("Prepared passive acceptance kit; no host provisioned or services started")


if __name__ == "__main__":
    main()
