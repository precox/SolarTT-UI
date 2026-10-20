#!/usr/bin/env python3
"""Audit on disposable Actions runners and prepare a bounded public PR proposal."""
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from dependency_policy import (ManualReview, REGISTRY, SHA, choose_target, findings,
                               fingerprint, index, review_target, validate_patch, version)
from security_check import PRIVATE, tool

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist/dependency-maintenance/proposal.json"
LIVE_RECEIPT = "Record live dependency maintenance invocation"


def require_runner():
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or not os.environ.get("GITHUB_WORKSPACE", "").startswith("/home/runner/work/")):
        raise RuntimeError("Dependency preparation requires a disposable GitHub Linux runner")


def database_snapshot():
    """Identify a clean on-disk database, never infer provenance from an audit exit."""
    args = ["git", "-C", str(PRIVATE / "advisory-db")]
    commit = subprocess.check_output(args + ["rev-parse", "--verify", "HEAD"],
                                     stderr=subprocess.PIPE, text=True).strip()
    dirty = subprocess.check_output(args + ["status", "--porcelain", "--untracked-files=all",
                                           "--ignore-submodules=none"], stderr=subprocess.PIPE)
    if not SHA.fullmatch(commit) or dirty:
        raise RuntimeError("Advisory database must be a clean Git snapshot")
    return commit


def audit(root, fetch=True):
    before = database_snapshot() if not fetch else None
    args = [tool("cargo-audit"), "audit", "--json", "--file", str(root / "Cargo.lock"),
            "--db", str(PRIVATE / "advisory-db")]
    if not fetch:
        args.append("--no-fetch")
    process = subprocess.run(args, cwd=root, capture_output=True, timeout=180)
    try:
        report = json.loads(process.stdout)
        if not fetch:
            after = database_snapshot()
            if after != before:
                raise ValueError("Advisory database changed during audit")
            # cargo-audit 0.22.2 opens the files directly with --no-fetch and
            # omits Git metadata. Recover only its explicitly null commit from
            # the verified clean repository, checked on both sides of the audit.
            database = report.get("database")
            if isinstance(database, dict) and "last-commit" in database and database["last-commit"] is None:
                database["last-commit"] = before
        findings(report, process.returncode)
    except (ValueError, TypeError):
        raise RuntimeError("RustSec audit failed; no healthy result or PR is inferred") from None
    return report, process.returncode


def command(args, root):
    process = subprocess.run(args, cwd=root, capture_output=True, timeout=240)
    if process.returncode:
        raise ManualReview("cargo_or_upstream_preparation_failed")


def prepare(root, report, code, base, registry=index, audit_after=None):
    database, observations = findings(report, code)
    old_lock = (root / "Cargo.lock").read_text()
    old_review = (root / "upstream/license-review.json").read_text()
    summary = {"schema": 1, "base": base, "audit_database": database,
               "before_lock_sha256": hashlib.sha256(old_lock.encode()).hexdigest(),
               "findings": observations, "decision": "healthy", "reason": "no_known_vulnerabilities",
               "target": None}
    if not observations:
        return {"summary": summary, "files": {}}
    summary.update(decision="manual", reason="manual_review_required")
    files = {}
    try:
        identities = {(r["package"], r["version"]) for r in observations}
        if len(identities) != 1:
            raise ManualReview("multiple_vulnerable_package_identities")
        name, current = next(iter(identities))
        version(current, stable=True)
        locked = [p for p in tomllib.loads(old_lock)["package"] if p["name"] == name and p["version"] == current]
        if len(locked) != 1 or locked[0].get("source") != REGISTRY:
            raise ManualReview("unsupported_dependency_source_or_identity")
        review = json.loads(old_review)
        approved = [p for p in review["packages"] if p["name"] == name and p["version"] == current]
        if len(approved) != 1:
            raise ManualReview("missing_exact_license_review")
        entries = registry(name)
        if entries.get(current, {}).get("cksum") != locked[0]["checksum"]:
            raise ValueError("Current lockfile does not match the official registry")
        target = choose_target(current, entries, observations)
        checksum = review_target(name, current, target, entries, approved[0])
        summary["target"] = {"package": name, "from": current, "to": target, "checksum": checksum}
        require_runner()
        command([sys.executable, str(root / "scripts/prepare_upstream.py")], root)
        command(["cargo", "update", "--manifest-path", str(root / "Cargo.toml"),
                 "-p", f"{name}@{current}", "--precise", target], root)
        approved[0]["version"] = target
        review["review_date"] = datetime.now(timezone.utc).date().isoformat()
        new_review = json.dumps(review, indent=2) + "\n"
        (root / "upstream/license-review.json").write_text(new_review)
        new_lock = (root / "Cargo.lock").read_text()
        validate_patch(old_lock, new_lock, old_review, new_review, summary["target"])
        command(["cargo", "metadata", "--locked", "--format-version", "1",
                 "--manifest-path", str(root / "Cargo.toml")], root)
        after, status = (audit_after or (lambda: audit(root, fetch=False)))()
        after_database, remaining = findings(after, status)
        if after_database != database:
            raise ValueError("Advisory database changed during candidate validation")
        if remaining:
            raise ManualReview("candidate_still_vulnerable")
        files = {"Cargo.lock": new_lock, "upstream/license-review.json": new_review}
        summary.update(decision="patch", reason="stable_patch_with_identical_notices")
    except ManualReview as error:
        summary.update(decision="manual", reason=str(error))
    finally:
        # The writable job publishes an artifact, not its working tree. Never
        # leave a partial resolution available to another step or manual PR.
        (root / "Cargo.lock").write_text(old_lock)
        (root / "upstream/license-review.json").write_text(old_review)
    identity = fingerprint(summary)
    summary["identity"] = identity
    files[f"docs/dependency-updates/{identity}.json"] = json.dumps(summary, indent=2) + "\n"
    return {"summary": summary, "files": files}


def main():
    require_runner()
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    proposal = prepare(ROOT, *audit(ROOT), base)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(proposal, indent=2) + "\n")
    summary = proposal["summary"]
    # Only structured public observations enter the artifact and summary.
    print(json.dumps(summary, indent=2))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f"vulnerabilities={len(summary['findings'])}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write("### Dependency maintenance\n\n")
            stream.write(f"Decision: **{summary['decision']}**; findings: **{len(summary['findings'])}**.\n\n")
            stream.write("PR preparation is not release, deployment or a claim about installed nodes.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Dependency preparation failed; inspect trusted CI locally; no PR inferred") from None
