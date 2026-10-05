#!/usr/bin/env python3
"""Package already-built binaries without installing or starting any service."""
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    deb_version = version.replace("-alpha.", "~alpha")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="solartt-package-") as folder:
        tree = Path(folder) / "root"
        def copy(source, target, mode=0o644):
            path = tree / target
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, path)
            path.chmod(mode)
        for binary in ("solartt-agent", "solartt-panel", "solartt-admin"):
            copy(ROOT / "target/release" / binary, "usr/bin/" + binary, 0o755)
        for unit in (ROOT / "packaging/systemd").glob("*.service"):
            copy(unit, "usr/lib/systemd/system/" + unit.name)
        for example in (ROOT / "examples").glob("*.toml"):
            copy(example, "usr/share/doc/solartt-ui/examples/" + example.name)
        for source in (ROOT / "docs").glob("*.md"):
            copy(source, "usr/share/doc/solartt-ui/" + source.name)
        for name in ("LICENSE", "README.md", "SECURITY.md", "CHANGELOG.md"):
            copy(ROOT / name, "usr/share/doc/solartt-ui/" + name)
        copy(ROOT / "upstream/pin.json", "usr/share/doc/solartt-ui/upstream-pin.json")
        copy(ROOT / "upstream/0001-managed-policy.patch", "usr/share/doc/solartt-ui/managed-policy.patch")
        notices = output / "third-party"
        if not notices.is_dir():
            raise SystemExit("Run scripts/licenses.py before packaging")
        shutil.copytree(notices, tree / "usr/share/doc/solartt-ui/third-party")
        control = tree / "DEBIAN"
        control.mkdir()
        (control / "control").write_text(f"""Package: solartt-ui
Version: {deb_version}
Architecture: amd64
Maintainer: SolarTT-UI contributors <noreply@github.com>
Depends: adduser, ca-certificates, libc6 (>= 2.39), libgcc-s1
Section: net
Priority: optional
Homepage: https://github.com/precox/SolarTT-UI
Description: Independent management for TrustTunnel
 Managed H2 endpoint, local web panel, durable payload quotas and profile export.
 Development build; configure explicitly before starting services.
""")
        for name in ("postinst", "prerm", "postrm"):
            copy(ROOT / "packaging/debian" / name, "DEBIAN/" + name, 0o755)
        deb = output / f"solartt-ui_{deb_version}_amd64.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(tree), str(deb)], check=True)
        archive = output / f"solartt-ui-{version}-linux-x86_64.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for path in sorted(tree.iterdir()):
                if path.name != "DEBIAN":
                    tar.add(path, arcname=path.name)
    metadata = {"version": version, "upstream": json.loads((ROOT / "upstream/pin.json").read_text()),
        "patch_sha256": hashlib.sha256((ROOT / "upstream/0001-managed-policy.patch").read_bytes()).hexdigest(),
        "cargo_lock_sha256": hashlib.sha256((ROOT / "Cargo.lock").read_bytes()).hexdigest()}
    (output / "build.json").write_text(json.dumps(metadata, indent=2) + "\n")
    files = [deb, archive, output / "build.json"]
    (output / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in files))
    print("Built development packages; no service installed or started")

if __name__ == "__main__":
    main()
