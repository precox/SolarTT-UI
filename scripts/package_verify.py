#!/usr/bin/env python3
"""Inspect development packages and their real ELF/runtime inputs on the CI runner."""
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARIES = ("solartt-agent", "solartt-panel", "solartt-admin")


def main():
    output = ROOT / "dist"
    debs = list(output.glob("*.deb"))
    archives = list(output.glob("solartt-ui-*.tar.gz"))
    if len(debs) != 1 or len(archives) != 1:
        raise SystemExit("Expected exactly one development deb and tar archive")
    for line in (output / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        if Path(name).name != name:
            raise SystemExit("Unsafe checksum filename")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected

    with tempfile.TemporaryDirectory(prefix="solartt-package-verify-") as folder:
        tree = Path(folder) / "deb"
        subprocess.run(["dpkg-deb", "--extract", str(debs[0]), str(tree)], check=True)
        with tarfile.open(archives[0]) as archive:
            tar_files = {}
            for member in archive:
                parts = Path(member.name).parts
                assert not member.name.startswith("/") and ".." not in parts
                assert not member.issym() and not member.islnk()
                if member.isfile():
                    tar_files[member.name] = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
            deb_files = {str(p.relative_to(tree)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in tree.rglob("*") if p.is_file()}
            assert tar_files == deb_files, "Deb and tar payloads differ"
        for name in deb_files:
            assert not any(part in (".dev", ".git", ".upstream", "private") for part in Path(name).parts)
            assert not name.endswith((".pem", ".key", ".sqlite", ".db", ".p12", ".pfx"))
        assert "usr/share/doc/solartt-ui/examples/haproxy.cfg" in deb_files
        control = subprocess.check_output(["dpkg-deb", "--field", str(debs[0]), "Depends"], text=True)
        records = []
        for name in BINARIES:
            path = tree / "usr/bin" / name
            assert path.stat().st_mode & 0o777 == 0o755
            dynamic = subprocess.check_output(["readelf", "-d", str(path)], text=True)
            needed = sorted(re.findall(r"\(NEEDED\).*?\[(.*?)\]", dynamic))
            versions = subprocess.check_output(["readelf", "--version-info", str(path)], text=True)
            glibc = sorted(set(re.findall(r"\bGLIBC_(\d+\.\d+(?:\.\d+)?)\b", versions)),
                           key=lambda v: tuple(map(int, v.split("."))))
            assert glibc and tuple(map(int, glibc[-1].split("."))) <= (2, 39)
            if "libstdc++.so.6" in needed:
                assert "libstdc++6" in control, "Undeclared C++ runtime dependency"
            linkage = subprocess.check_output(["ldd", str(path)], text=True)
            assert "not found" not in linkage
            print(f"{name}: NEEDED {needed}; maximum GLIBC {glibc[-1]}")
            records.append({"binary": name, "needed": needed, "glibc_versions": glibc,
                            "runtime_linkage": linkage.splitlines()})
    versions = {}
    for label, command in {
        "compiler": ["cc", "--version"],
        "cmake": ["cmake", "--version"],
        "openssl": ["openssl", "version"],
        "haproxy": ["haproxy", "-v"],
        "caddy_fixture": [str(ROOT / ".dev/caddy-fixture/caddy"), "version"],
        "rustc": ["rustc", "--version"],
        "python": ["python3", "--version"],
        "node": ["node", "--version"],
    }.items():
        versions[label] = subprocess.check_output(command, text=True).splitlines()[0]
    query_format = "$" + "{Package} " + "$" + "{Version}\n"
    system = subprocess.check_output(["dpkg-query", "-W", "-f=" + query_format,
                                     "libc6", "libgcc-s1", "libstdc++6", "cmake", "haproxy", "openssl"],
                                    text=True).splitlines()
    result = {"packages_identical": True, "checksums_verified": True,
              "declared_dependencies": control.strip(), "elf": records,
              "runner_tools": versions, "runner_packages": system,
              "scope": "ABI/linkage/provenance checks; not a complete native or OS vulnerability audit"}
    (output / "runtime-dependencies.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Package payloads/checksums, ELF ABI and runtime libraries verified")


if __name__ == "__main__":
    main()
