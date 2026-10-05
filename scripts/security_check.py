#!/usr/bin/env python3
"""Redacted secret scans and RustSec audit using checksum-pinned public tools.

Never scan the ignored development directory: it intentionally holds local keys.
History checks require a full clone. Artifact scans unpack packages before scanning.
"""
import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".dev/security"
TOOLS = {
    "gitleaks": (
        "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz",
        "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
    ),
    "cargo-audit": (
        "https://github.com/rustsec/rustsec/releases/download/cargo-audit/v0.22.2/cargo-audit-x86_64-unknown-linux-musl-v0.22.2.tgz",
        "7fb9497f8594b389e5fce5ef9b92db08432996895b2e0c5a0167a69ed445c428",
    ),
}


def tool(name):
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    PRIVATE.chmod(0o700)
    url, digest = TOOLS[name]
    archive = PRIVATE / (name + "-verified.tar.gz")
    if not archive.exists():
        archive.write_bytes(urllib.request.urlopen(url, timeout=60).read())
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise SystemExit(f"{name} archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        matches = [m for m in tar if m.isfile() and Path(m.name).name == name]
        if len(matches) != 1:
            raise SystemExit(f"Unexpected {name} archive")
        executable = PRIVATE / name
        executable.write_bytes(tar.extractfile(matches[0]).read())
        executable.chmod(0o700)
    return str(executable)


def secrets(mode, path, report_name):
    report = PRIVATE / report_name
    report.unlink(missing_ok=True)
    command = [tool("gitleaks"), mode, "--redact=100", "--max-decode-depth=2",
               "--config=" + str(ROOT / ".gitleaks.toml"), "--report-format=json",
               "--report-path=" + str(report)]
    if mode == "git":
        command.append("--log-opts=--all")
    result = subprocess.run(command + [str(path)], cwd=ROOT, capture_output=True, text=True)
    if not report.exists() or result.returncode not in (0, 1):
        raise SystemExit(f"Secret scanner failed for {report_name}; inspect locally")
    findings = json.loads(report.read_text())
    print(f"{report_name}: {len(findings)} findings")
    for finding in findings:
        # Never emit matched contents, even on a failing CI run.
        print(f"  {finding['RuleID']}: {finding['File']}:{finding['StartLine']}")
    if findings or result.returncode:
        raise SystemExit("Secret scan failed")


def source():
    shallow = subprocess.check_output(["git", "rev-parse", "--is-shallow-repository"], cwd=ROOT)
    if shallow.strip() != b"false":
        raise SystemExit("Fetch full history before scanning")
    secrets("git", ROOT, "history.json")
    # Scan tracked working files too, including staged changes, without local secrets.
    with tempfile.TemporaryDirectory(prefix="solartt-source-") as folder:
        tree = Path(folder)
        for name in subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0"):
            if not name:
                continue
            relative = Path(name.decode())
            original = ROOT / relative
            if original.is_symlink():
                raise SystemExit("Tracked symlinks are not allowed")
            target = tree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
        secrets("dir", tree, "source.json")
    result = subprocess.run([tool("cargo-audit"), "audit", "--json", "--db",
                             str(PRIVATE / "advisory-db")], cwd=ROOT, capture_output=True, text=True)
    if not result.stdout:
        raise SystemExit("RustSec audit failed to produce a report")
    report = json.loads(result.stdout)
    (PRIVATE / "dependencies.json").write_text(json.dumps(report, indent=2) + "\n")
    print("RustSec database:", report["database"]["last-commit"])
    print("Dependency vulnerabilities:", report["vulnerabilities"]["count"])
    for finding in report["vulnerabilities"]["list"]:
        print(f"  {finding['advisory']['id']}: {finding['package']['name']} {finding['package']['version']}")
    for kind, findings in report.get("warnings", {}).items():
        for finding in findings:
            print(f"  warning {kind}: {finding['package']['name']} {finding['package']['version']}")
    if result.returncode:
        raise SystemExit("Dependency audit failed")


def artifacts():
    output = ROOT / "dist"
    packages = list(output.glob("*.deb")) + list(output.glob("*.tar.gz"))
    if not packages:
        raise SystemExit("No packages to scan")
    with tempfile.TemporaryDirectory(prefix="solartt-artifacts-") as folder:
        tree = Path(folder)
        for i, package in enumerate(packages):
            destination = tree / str(i)
            destination.mkdir()
            if package.suffix == ".deb":
                subprocess.run(["dpkg-deb", "--raw-extract", str(package), str(destination)], check=True)
            else:
                with tarfile.open(package) as archive:
                    archive.extractall(destination, filter="data")
        secrets("dir", tree, "packages.json")
    secrets("dir", output, "artifact-files.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["source", "artifacts"])
    args = parser.parse_args()
    source() if args.mode == "source" else artifacts()
