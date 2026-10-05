#!/usr/bin/env python3
"""Regenerate the managed patch against the verified upstream archive.

Run after editing .upstream. Review the resulting diff before committing it.
"""
import difflib
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["lib/src/lib.rs", "lib/src/core.rs", "lib/src/managed.rs",
         "lib/src/tunnel.rs", "lib/src/pipe.rs", "lib/src/udp_pipe.rs",
         "lib/src/tcp_forwarder.rs", "lib/src/udp_forwarder.rs"]

def main():
    pin = json.loads((ROOT / "upstream/pin.json").read_text())
    url = f"https://codeload.github.com/{pin['repository']}/tar.gz/{pin['commit']}"
    data = urllib.request.urlopen(url, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != pin["archive_sha256"]:
        raise SystemExit("Upstream archive checksum mismatch")
    output = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        originals = {"/".join(Path(m.name).parts[1:]): m for m in archive.getmembers() if m.isfile()}
        for name in FILES:
            before = archive.extractfile(originals[name]).read().decode() if name in originals else ""
            after = (ROOT / ".upstream" / name).read_text()
            if before == after:
                continue
            output.append(f"diff --git a/{name} b/{name}\n")
            if name not in originals:
                output.append("new file mode 100644\n")
            output.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                fromfile=f"a/{name}" if before else "/dev/null", tofile=f"b/{name}"))
    (ROOT / "upstream/0001-managed-policy.patch").write_text("".join(output))
    print("Updated managed patch against verified upstream archive")

if __name__ == "__main__":
    main()
