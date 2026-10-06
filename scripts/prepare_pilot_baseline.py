#!/usr/bin/env python3
"""Reconstruct the original schema-1 release source for a disposable pilot runner."""
import hashlib
import io
import json
import os
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux":
        raise SystemExit("Baseline preparation is restricted to the disposable pilot runner")
    pin = json.loads((ROOT / "upstream/pilot-baseline-pin.json").read_text())
    destination = ROOT / ".dev/pilot-baseline"
    if destination.exists():
        raise SystemExit("Pilot baseline destination must be new")
    data = urllib.request.urlopen(
        f"https://codeload.github.com/{pin['repository']}/tar.gz/{pin['commit']}", timeout=60).read()
    if hashlib.sha256(data).hexdigest() != pin["archive_sha256"]:
        raise SystemExit("Baseline source checksum mismatch")
    destination.mkdir(parents=True, mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            parts = Path(member.name).parts[1:]
            if not parts:
                continue
            if member.issym() or member.islnk() or ".." in parts:
                raise SystemExit("Unsafe baseline archive entry")
            if member.isfile():
                target = destination.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
    # Give git apply its own root, rather than inheriting the surrounding checkout.
    subprocess.run(["git", "init", "-q", str(destination)], check=True)
    subprocess.run(["python3", "scripts/prepare_upstream.py"], cwd=destination, check=True)
    # Reuse compiler outputs only; current tested packages are downloaded separately.
    (destination / "target").symlink_to(ROOT / "target", target_is_directory=True)
    print(f"Prepared original {pin['version']} source at pinned commit {pin['commit']}")


if __name__ == "__main__":
    main()
