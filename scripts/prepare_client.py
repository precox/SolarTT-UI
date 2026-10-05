#!/usr/bin/env python3
"""Download the pinned official CLI for isolated compatibility tests only."""
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    pin = json.loads((ROOT / "upstream/client-pin.json").read_text())
    url = f"https://github.com/{pin['repository']}/releases/download/{pin['version']}/{pin['asset']}"
    data = urllib.request.urlopen(url, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != pin["archive_sha256"]:
        raise SystemExit("Official CLI archive checksum mismatch")
    destination = ROOT / ".dev/official-client"
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        candidates = [m for m in archive.getmembers() if m.isfile() and
            not m.issym() and not m.islnk() and Path(m.name).name == "trusttunnel_client"]
        if len(candidates) != 1:
            raise SystemExit("Expected exactly one official CLI executable")
        executable = destination / "trusttunnel_client"
        executable.write_bytes(archive.extractfile(candidates[0]).read())
        executable.chmod(0o755)
    print(f"Prepared official TrustTunnel CLI {pin['version']} for testing")


if __name__ == "__main__":
    main()
