"""Policy and publication tests using synthetic data and a fake GitHub API."""
import copy
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from dependency_policy import (ManualReview, choose_target, findings, fingerprint,
                               matches, review_target, validate_patch, version)
from github_api import DOWNSTREAM, GitHubError
from maintain_dependencies import audit, database_snapshot, prepare
from publish_dependency_update import publish, validate

BASE = "a" * 40
HEAD = "b" * 40
OLD = 'version = 4\n[[package]]\nname = "example"\nversion = "1.2.3"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\nchecksum = "' + "c" * 64 + '"\n'
NEW = OLD.replace('version = "1.2.3"', 'version = "1.2.4"').replace("c" * 64, "d" * 64)
ENTRY = {"name": "example", "version": "1.2.3", "declared_license": "ISC", "selected_license": "ISC",
         "notices_sha256": {"LICENSE": hashlib.sha256(b"synthetic notice").hexdigest()}}
REVIEW = json.dumps({"review_date": "2026-10-20", "packages": [ENTRY]})
TARGET = {"package": "example", "from": "1.2.3", "to": "1.2.4", "checksum": "d" * 64}
OBSERVATION = {"package": "example", "version": "1.2.3", "advisory": "RUSTSEC-2026-0382", "patched": [">=1.2.4, <1.3.0-alpha.1"]}


def audit_report(values=None):
    values = [OBSERVATION] if values is None else values
    return {"database": {"last-commit": "e" * 40}, "vulnerabilities": {"count": len(values), "list": [
        {"package": {"name": v["package"], "version": v["version"]}, "advisory": {"id": v["advisory"]},
         "versions": {"patched": v["patched"]}} for v in values]}}


def proposal():
    summary = {"schema": 1, "base": BASE, "audit_database": "e" * 40,
               "before_lock_sha256": hashlib.sha256(OLD.encode()).hexdigest(),
               "findings": [OBSERVATION], "decision": "patch",
               "reason": "stable_patch_with_identical_notices", "target": TARGET}
    summary["identity"] = fingerprint(summary)
    reviewed = json.loads(REVIEW)
    reviewed["packages"][0]["version"] = "1.2.4"
    files = {"Cargo.lock": NEW, "upstream/license-review.json": json.dumps(reviewed)}
    files[f"docs/dependency-updates/{summary['identity']}.json"] = json.dumps(summary, indent=2) + "\n"
    return {"summary": summary, "files": files}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / "upstream").mkdir()
        (self.root / "Cargo.lock").write_text(OLD)
        (self.root / "upstream/license-review.json").write_text(REVIEW)

    def test_numerical_patch_selection_ignores_api_order_yanked_beta_major_minor(self):
        records = {v: {"yanked": False} for v in ("1.2.10", "1.3.0", "2.0.0", "1.2.5-beta.1", "1.2.4", "1.2.5")}
        records["1.2.4"]["yanked"] = True
        self.assertEqual(choose_target("1.2.3", records, [OBSERVATION]), "1.2.5")
        self.assertTrue(matches("1.2.4", ">=1.2.4, <1.3.0-alpha.1"))
        self.assertFalse(matches("1.3.0", "<1.3.0-alpha.1"))
        with self.assertRaises(ManualReview):
            matches("1.2.4", "^1.2.4")
        with self.assertRaises(ManualReview):
            choose_target("1.2.3", {"1.2.4": {"yanked": False}}, [{**OBSERVATION, "patched": []}])

    def test_audit_errors_cannot_become_healthy(self):
        for data, code in [(audit_report([]), 1), (audit_report(), 0), ({}, 0),
                           ({"database": {"last-commit": "e" * 40}, "vulnerabilities": {"count": False, "list": []}}, 0)]:
            with self.assertRaises(ValueError):
                findings(data, code)
        self.assertEqual(findings(audit_report([]), 0)[1], [])

    def test_build_metadata_findings_produce_publishable_manual_report_without_cargo(self):
        locked = tomllib.loads((Path(__file__).resolve().parents[1] / "Cargo.lock").read_text())["package"]
        examples = [(p["name"], p["version"]) for p in locked if "+" in p["version"]]
        self.assertTrue(examples)
        for name, current in examples:
            with self.subTest(package=name, version=current):
                self.root.joinpath("Cargo.lock").write_text(OLD.replace('name = "example"', f'name = "{name}"')
                                                          .replace('version = "1.2.3"', f'version = "{current}"'))
                observation = {**OBSERVATION, "package": name, "version": current}
                data = audit_report([observation])
                self.assertEqual(findings(data, 1)[1], [observation])
                with patch("maintain_dependencies.command") as command, \
                        patch("maintain_dependencies.require_runner") as runner, \
                        patch("maintain_dependencies.review_target") as review:
                    candidate = prepare(self.root, data, 1, BASE,
                                        registry=lambda _: self.fail("Metadata must not trigger registry access"))
                self.assertEqual(candidate["summary"]["decision"], "manual")
                self.assertEqual(candidate["summary"]["reason"], "build_metadata_requires_manual_review")
                self.assertEqual(candidate["summary"]["findings"][0]["version"], current)
                self.assertEqual(len(candidate["files"]), 1)
                validate(candidate, self.root)
                api = API(candidate)
                publish(api, candidate["summary"], candidate["files"], "main")
                request = next(payload for method, path, payload in api.calls
                               if method == "POST" and path.endswith("/pulls"))
                self.assertTrue(request["draft"])
                command.assert_not_called()
                runner.assert_not_called()
                review.assert_not_called()

    def test_semver_metadata_is_valid_input_but_never_an_automatic_target(self):
        for value in ("1.2.3+001", "1.2.3-beta.1+build.02", "0.11.1+wasi-snapshot-preview1"):
            self.assertEqual(findings(audit_report([{**OBSERVATION, "version": value}]), 1)[1][0]["version"], value)
            with self.assertRaises(ManualReview):
                version(value, stable=True)
        for value in ("1.2.3+", "1.2.3+build..1", "1.2.3+build/1", "1.2.3-01", "1.2.3-beta.01+build"):
            with self.assertRaises(ValueError):
                findings(audit_report([{**OBSERVATION, "version": value}]), 1)
        records = {v: {"yanked": False} for v in ("1.2.4+build.1", "1.2.5", "1.2.6-beta.1+build")}
        self.assertEqual(choose_target("1.2.3", records, [OBSERVATION]), "1.2.5")
        reviewed = json.loads(REVIEW)
        reviewed["packages"][0]["version"] = "1.2.4+build.1"
        with self.assertRaises((ValueError, ManualReview)):
            validate_patch(OLD, NEW.replace("1.2.4", "1.2.4+build.1"), REVIEW, json.dumps(reviewed),
                           {**TARGET, "to": "1.2.4+build.1"})

    def test_no_fetch_audit_requires_clean_unchanged_database_provenance(self):
        response = audit_report([])
        response["database"]["last-commit"] = None
        with patch("maintain_dependencies.tool", return_value="/verified/cargo-audit"), \
                patch("maintain_dependencies.subprocess.run") as run, \
                patch("maintain_dependencies.database_snapshot", side_effect=["e" * 40, "e" * 40]):
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps(response).encode())
            report, code = audit(self.root, fetch=False)
            self.assertEqual(findings(report, code), ("e" * 40, []))
            self.assertIn("--no-fetch", run.call_args.args[0])
        for commits, payload, code in [(["e" * 40, "f" * 40], response, 0),
                                        (["e" * 40, "e" * 40], response, 2),
                                        (["e" * 40, "e" * 40], {"database": {}}, 0)]:
            with patch("maintain_dependencies.tool", return_value="/verified/cargo-audit"), \
                    patch("maintain_dependencies.subprocess.run", return_value=subprocess.CompletedProcess(
                        [], code, json.dumps(payload).encode())), \
                    patch("maintain_dependencies.database_snapshot", side_effect=commits), \
                    self.assertRaises(RuntimeError):
                audit(self.root, fetch=False)
        with patch("maintain_dependencies.subprocess.check_output", side_effect=["e" * 40, b"?? injected.md\n"]), \
                self.assertRaises(RuntimeError):
            database_snapshot()
        with patch("maintain_dependencies.subprocess.check_output", side_effect=["e" * 40, b""]):
            self.assertEqual(database_snapshot(), "e" * 40)

    def test_healthy_and_complex_proposals_make_no_cargo_or_github_calls(self):
        healthy = prepare(self.root, audit_report([]), 0, BASE)
        self.assertEqual(healthy["files"], {})
        multiple = audit_report([OBSERVATION, {**OBSERVATION, "package": "other"}])
        manual = prepare(self.root, multiple, 1, BASE)
        self.assertEqual(manual["summary"]["decision"], "manual")
        self.assertEqual(len(manual["files"]), 1)
        self.assertEqual((self.root / "Cargo.lock").read_text(), OLD)

    def test_publisher_rejects_code_paths_graph_and_notice_tampering(self):
        candidate = proposal()
        validate(candidate, self.root)
        for mutate in (lambda p: p["files"].update({"scripts/exfiltrate.py": "bad"}),
                       lambda p: p["files"].update({"Cargo.lock": NEW + '\n[[package]]\nname="extra"\nversion="1.0.0"\n'}),
                       lambda p: p["files"].update({"upstream/license-review.json": p["files"]["upstream/license-review.json"].replace("ISC", "MIT")})):
            data = copy.deepcopy(candidate)
            mutate(data)
            with self.assertRaises((ValueError, ManualReview)):
                validate(data, self.root)
        with self.assertRaises(ValueError):
            validate_patch(OLD, NEW, REVIEW, candidate["files"]["upstream/license-review.json"], {**TARGET, "to": "1.3.0"})

    def test_archive_checksum_notices_and_metadata_must_match(self):
        def archive(notice=b"synthetic notice", license_file=False):
            stream = io.BytesIO()
            manifest = b'[package]\nname="example"\nversion="1.2.4"\nlicense="ISC"\n'
            if license_file:
                manifest += b'license-file="LICENSE"\n'
            with tarfile.open(fileobj=stream, mode="w:gz") as tar:
                for path, data in [("Cargo.toml", manifest), ("LICENSE", notice)]:
                    info = tarfile.TarInfo("example-1.2.4/" + path)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            return stream.getvalue()
        for changed, file_option in [(False, False), (True, False), (False, True)]:
            data = archive(b"different notice" if changed else b"synthetic notice", file_option)
            entries = {"1.2.3": {"deps": []}, "1.2.4": {"deps": [], "cksum": hashlib.sha256(data).hexdigest()}}
            with patch("dependency_policy.download", return_value=data):
                if changed or file_option:
                    with self.assertRaises(ManualReview):
                        review_target("example", "1.2.3", "1.2.4", entries, ENTRY)
                else:
                    self.assertEqual(review_target("example", "1.2.3", "1.2.4", entries, ENTRY), entries["1.2.4"]["cksum"])
                entries["1.2.4"]["cksum"] = "0" * 64
                with self.assertRaises(ValueError):
                    review_target("example", "1.2.3", "1.2.4", entries, ENTRY)


class API:
    def __init__(self, candidate):
        self.candidate = candidate
        self.prs = []
        self.branch = False
        self.runs = [{"head_sha": HEAD, "event": "pull_request", "conclusion": "action_required"}]
        self.calls = []
        self.lose_pr_response = False
        self.main = BASE

    def pages(self, path):
        return iter(self.prs)

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET":
            if "/compare/" in path:
                return {"status": "ahead", "total_commits": 1, "merge_base_commit": {"sha": BASE},
                        "files": [{"filename": p} for p in self.candidate["files"]]}
            if "/git/trees/" in path:
                return {"truncated": False, "tree": [{"path": p, "mode": "100644", "sha": hashlib.sha1(
                    b"blob " + str(len(v.encode())).encode() + b"\0" + v.encode()).hexdigest()} for p, v in self.candidate["files"].items()]}
            if "/git/commits/" in path:
                return {"tree": {"sha": "f" * 40}}
            if path.endswith("/git/ref/heads/main"):
                return {"object": {"sha": self.main}}
            if "/git/ref/heads/automation/" in path:
                if not self.branch:
                    raise GitHubError("GitHub GET ref: HTTP 404")
                return {"object": {"sha": HEAD}}
            if "/actions/workflows/ci.yml/runs?" in path:
                return {"workflow_runs": self.runs}
        if method == "POST":
            if path.endswith("/git/refs"):
                self.branch = True
            if path.endswith("/pulls"):
                pr = {"user": {"id": 41898282, "type": "Bot", "login": "github-actions[bot]"},
                      "head": {"sha": HEAD, "ref": "automation/security-" + self.candidate["summary"]["identity"],
                               "repo": {"full_name": DOWNSTREAM}}, "number": 9, "state": "open"}
                self.prs.append(pr)
                if self.lose_pr_response:
                    self.lose_pr_response = False
                    raise GitHubError("Lost synthetic POST response")
                return pr
            if path.endswith("/dispatches"):
                self.runs.append({"head_sha": HEAD, "event": "workflow_dispatch"})
                return None
            return {"sha": HEAD}
        raise AssertionError((method, path))


class PublicationTests(unittest.TestCase):
    def test_creation_explicit_dispatch_and_repeated_closed_pr_deduplication(self):
        p = proposal()
        api = API(p)
        self.assertEqual(publish(api, p["summary"], p["files"], "main")["pr"], 9)
        publish(api, p["summary"], p["files"], "main")
        api.prs[0]["state"] = "closed"
        self.assertEqual(publish(api, p["summary"], p["files"], "main")["action"], "already_triaged")
        writes = [(path, data) for method, path, data in api.calls if method == "POST"]
        self.assertEqual(sum(path.endswith("/pulls") for path, _ in writes), 1)
        self.assertEqual(sum(path.endswith("/dispatches") for path, _ in writes), 1)
        self.assertFalse(any(method == "PATCH" for method, _, _ in api.calls))
        self.assertTrue(all(data["ref"].startswith("refs/heads/automation/security-") for path, data in writes if path.endswith("/git/refs")))

    def test_lost_pr_response_reconciles_without_duplicate_or_force_push(self):
        p = proposal()
        api = API(p)
        api.lose_pr_response = True
        with self.assertRaises(GitHubError):
            publish(api, p["summary"], p["files"], "main")
        publish(api, p["summary"], p["files"], "main")
        self.assertEqual(len(api.prs), 1)

    def test_moved_default_branch_stops_before_first_write(self):
        p = proposal()
        api = API(p)
        api.main = "f" * 40
        with self.assertRaises(ValueError):
            publish(api, p["summary"], p["files"], "main")
        self.assertFalse(any(method != "GET" for method, _, _ in api.calls))


if __name__ == "__main__":
    unittest.main()
