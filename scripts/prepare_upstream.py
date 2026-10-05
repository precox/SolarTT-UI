#!/usr/bin/env python3
"""Reconstruct a pinned, reviewed dependency; never read production state."""
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = json.loads((ROOT / "upstream/pin.json").read_text())
DEST = ROOT / ".upstream"
MARKER = DEST / ".solartt-prepared"

def main():
    patches = sorted((ROOT / "upstream").glob("*.patch"))
    stamp = hashlib.sha256(json.dumps(PIN, sort_keys=True).encode() +
        b"".join(p.read_bytes() for p in patches)).hexdigest()
    if MARKER.is_file() and MARKER.read_text().strip() == stamp:
        print("Pinned upstream already prepared")
        return
    url = f"https://codeload.github.com/{PIN['repository']}/tar.gz/{PIN['commit']}"
    data = urllib.request.urlopen(url, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != PIN["archive_sha256"]:
        raise SystemExit("Upstream archive checksum mismatch")
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts[1:]
            if not parts:
                continue
            if ".." in parts or member.issym() or member.islnk():
                raise SystemExit("Unsafe archive entry")
            if not member.isfile():
                continue
            target = DEST.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    for patch in patches:
        subprocess.run(["git", "apply", "--check", "--directory=.upstream", str(patch)],
            cwd=ROOT, check=True)
        subprocess.run(["git", "apply", "--directory=.upstream", str(patch)],
            cwd=ROOT, check=True)
    MARKER.write_text(stamp + "\n")
    print("Prepared pinned TrustTunnel with", len(patches), "patches")

if __name__ == "__main__":
    main()
