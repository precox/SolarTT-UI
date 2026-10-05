#!/usr/bin/env python3
"""Prepare an official, checksum-pinned Caddy for disposable runner tests only."""
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    pin = json.loads((ROOT / "upstream/caddy-fixture-pin.json").read_text())
    url = f"https://github.com/{pin['repository']}/releases/download/{pin['version']}/{pin['asset']}"
    data = urllib.request.urlopen(url, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != pin["archive_sha256"]:
        raise SystemExit("Caddy fixture archive checksum mismatch")
    destination = ROOT / ".dev/caddy-fixture"
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        candidates = [m for m in archive if m.isfile() and Path(m.name).name == "caddy"]
        if len(candidates) != 1:
            raise SystemExit("Expected exactly one Caddy executable")
        executable = destination / "caddy"
        executable.write_bytes(archive.extractfile(candidates[0]).read())
        executable.chmod(0o700)
    print(f"Prepared Caddy {pin['version']} for isolated tests; no host service changed")


if __name__ == "__main__":
    main()
