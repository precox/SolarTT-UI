#!/usr/bin/env python3
"""Verify published alpha.5/alpha.6; extract ONLY on a disposable runner."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(folder, pin):
    assets = pin["assets_sha256"]
    for name, digest in assets.items():
        if Path(name).name != name or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Unsafe baseline pin")
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Published baseline asset checksum mismatch")
    metadata = json.loads((folder / "build.json").read_text())
    if metadata["version"] != pin["version"] or metadata["source_commit"] != pin["commit"]:
        raise ValueError("Published baseline source identity mismatch")
    manifest = {}
    for line in (folder / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if (Path(name).name != name or name in manifest
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Invalid published baseline manifest")
        manifest[name] = digest
    if any(manifest.get(name) != digest for name, digest in assets.items() if name != "SHA256SUMS"):
        raise ValueError("Published baseline manifest disagrees with pin")
    packages = [name for name in assets if name.endswith(".deb")]
    if len(packages) != 1:
        raise ValueError("Expected exactly one pinned baseline deb")
    return folder / packages[0]


def main(baseline="alpha5"):
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or os.environ.get("SOLARTT_PILOT_DISPOSABLE") != "1"
            or not str(ROOT).startswith("/home/runner/work/")):
        raise SystemExit("Published baseline extraction requires a disposable GitHub runner")
    if baseline not in {"alpha5", "alpha6"}:
        raise SystemExit("Unknown published baseline")
    pin = json.loads((ROOT / f"upstream/upgrade-{baseline}-pin.json").read_text())
    destination = ROOT / f".dev/{baseline}-baseline"
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name in pin["assets_sha256"]:
        if Path(name).name != name:
            raise SystemExit("Unsafe baseline filename")
        url = f"https://github.com/{pin['repository']}/releases/download/{pin['tag']}/{name}"
        (destination / name).write_bytes(urllib.request.urlopen(url, timeout=60).read())
    package = verify(destination, pin)
    if subprocess.check_output(["dpkg-deb", "-f", str(package), "Version"], text=True).strip() != pin["version"].replace("-alpha.", "~alpha"):
        raise SystemExit("Unexpected baseline Debian version")
    subprocess.run(["dpkg-deb", "--extract", str(package), str(destination / "root")], check=True)
    print("Verified published", baseline, "package at source", pin["commit"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", choices=["alpha5", "alpha6"], default="alpha5")
    main(parser.parse_args().baseline)
