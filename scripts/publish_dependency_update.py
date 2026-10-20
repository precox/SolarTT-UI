#!/usr/bin/env python3
"""Publish only bounded data from the same trusted default-branch workflow."""
import hashlib
import json
import os
import re
import tomllib
from pathlib import Path

from dependency_policy import CRATE, SHA, VERSION, fingerprint, validate_patch
from github_api import DOWNSTREAM, GitHubAPI, GitHubError

ROOT = Path(__file__).resolve().parents[1]
BASE = f"/repos/{DOWNSTREAM}"
BOT_ID = 41898282
REASONS = {"stable_patch_with_identical_notices", "multiple_vulnerable_package_identities",
           "unsupported_dependency_source_or_identity", "missing_exact_license_review",
           "noncanonical_or_prerelease_version", "unsupported_advisory_range",
           "no_supported_stable_patch", "dependency_features_or_msrv_changed",
           "registry_object_exceeds_limit", "unsupported_crate_archive",
           "crate_expansion_exceeds_limit", "duplicate_crate_notice",
           "license_or_notice_review_required", "cargo_or_upstream_preparation_failed",
           "resolved_graph_changed", "candidate_still_vulnerable"}


def sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("Invalid Git identity")
    return value


def validate(proposal, root=ROOT):
    summary, files = proposal["summary"], proposal["files"]
    keys = {"schema", "base", "audit_database", "before_lock_sha256", "findings", "decision", "reason", "target"}
    if summary.get("decision") != "healthy":
        keys.add("identity")
    if set(proposal) != {"summary", "files"} or set(summary) != keys:
        raise ValueError("Unexpected proposal fields")
    if (summary.get("schema") != 1 or summary.get("decision") not in ("healthy", "patch", "manual")
            or not isinstance(files, dict) or len(files) > 3
            or any(not isinstance(v, str) or len(v.encode()) > 1024 * 1024 for v in files.values())):
        raise ValueError("Invalid proposal schema")
    sha(summary["base"])
    sha(summary["audit_database"])
    old_lock = (root / "Cargo.lock").read_text()
    if hashlib.sha256(old_lock.encode()).hexdigest() != summary["before_lock_sha256"]:
        raise ValueError("Proposal does not match trusted checkout")
    observations = summary["findings"]
    locked = {(p["name"], p["version"]) for p in tomllib.loads(old_lock)["package"]}
    if not isinstance(observations, list) or len(observations) > 200:
        raise ValueError("Invalid findings")
    for observation in observations:
        if (set(observation) != {"package", "version", "advisory", "patched"}
                or not CRATE.fullmatch(observation["package"])
                or not VERSION.fullmatch(observation["version"])
                or (observation["package"], observation["version"]) not in locked
                or not re.fullmatch(r"RUSTSEC-[0-9]{4}-[0-9]{4}", observation["advisory"])
                or not isinstance(observation["patched"], list)
                or any(not isinstance(v, str) or len(v) > 200 for v in observation["patched"])):
            raise ValueError("Invalid finding identity")
    target = summary["target"]
    if target is not None and (not isinstance(target, dict)
            or set(target) != {"package", "from", "to", "checksum"}
            or not CRATE.fullmatch(target["package"]) or not VERSION.fullmatch(target["from"])
            or not VERSION.fullmatch(target["to"]) or not re.fullmatch(r"[0-9a-f]{64}", target["checksum"])):
        raise ValueError("Invalid target metadata")
    if summary["decision"] == "healthy":
        if files or observations or summary["target"] is not None or summary["reason"] != "no_known_vulnerabilities":
            raise ValueError("Invalid healthy proposal")
        return summary, files
    if not observations or summary["reason"] not in REASONS:
        raise ValueError("Invalid proposed decision")
    identity = fingerprint(summary)
    if summary.get("identity") != identity:
        raise ValueError("Proposal identity mismatch")
    report = f"docs/dependency-updates/{identity}.json"
    expected = {report}
    if summary["decision"] == "patch":
        expected.update(("Cargo.lock", "upstream/license-review.json"))
        target = summary["target"]
        if (set(target) != {"package", "from", "to", "checksum"}
                or any((r["package"], r["version"]) != (target["package"], target["from"]) for r in observations)):
            raise ValueError("Target does not match audit findings")
        validate_patch(old_lock, files["Cargo.lock"], (root / "upstream/license-review.json").read_text(),
                       files["upstream/license-review.json"], target)
    if set(files) != expected or files.get(report) != json.dumps(summary, indent=2) + "\n":
        raise ValueError("Only the validated lock/review and a structured report may change")
    return summary, files


def optional(api, path):
    try:
        return api.request("GET", path)
    except GitHubError as error:
        if ": HTTP 404" not in str(error):
            raise
        return None


def bot(pr):
    author = pr.get("user", {})
    return author.get("id") == BOT_ID and author.get("type") == "Bot" and author.get("login") == "github-actions[bot]"


def verify_branch(api, base, head, files):
    comparison = api.request("GET", f"{BASE}/compare/{sha(base)}...{sha(head)}")
    if (comparison.get("status") != "ahead" or comparison.get("total_commits") != 1
            or comparison.get("merge_base_commit", {}).get("sha") != base
            or {p["filename"] for p in comparison.get("files", [])} != set(files)):
        raise ValueError("Existing branch has unapproved changes; never overwrite or dispatch it")
    commit = api.request("GET", f"{BASE}/git/commits/{head}")
    tree = api.request("GET", f"{BASE}/git/trees/{sha(commit['tree']['sha'])}?recursive=1")
    if tree.get("truncated") is not False:
        raise ValueError("Incomplete branch tree")
    entries = {entry["path"]: entry for entry in tree["tree"]}
    for path, text in files.items():
        data = text.encode()
        digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if entries.get(path, {}).get("sha") != digest or entries[path].get("mode") != "100644":
            raise ValueError("Existing branch content differs; manual investigation required")


def dispatch(api, branch, head, summary, files):
    runs = api.request("GET", f"{BASE}/actions/workflows/ci.yml/runs?head_sha={sha(head)}&per_page=100")
    if not isinstance(runs.get("workflow_runs"), list):
        raise ValueError("Invalid CI response")
    if any(r.get("head_sha") == head and r.get("event") == "workflow_dispatch"
           for r in runs["workflow_runs"]):
        return "already_requested"
    # A reviewed branch can have human edits: don't launch a privileged ref's
    # workflow unless its entire delta is still the approved, non-code data.
    verify_branch(api, summary["base"], head, files)
    api.request("POST", f"{BASE}/actions/workflows/ci.yml/dispatches", {"ref": branch})
    return "requested"


def publish(api, summary, files, default_branch):
    if summary["decision"] == "healthy":
        return {"action": "healthy"}
    identity = summary["identity"]
    branch = "automation/security-" + identity
    marker = "<!-- solartt-dependency-maintenance:" + identity + " -->"
    all_prs = list(api.pages(f"{BASE}/pulls?state=all"))
    matches = [pr for pr in all_prs if bot(pr)
               and pr.get("head", {}).get("ref") == branch
               and pr.get("head", {}).get("repo", {}).get("full_name") == DOWNSTREAM]
    if len(matches) > 1:
        raise ValueError("Multiple managed PRs; consolidate manually")
    if matches:
        pr = matches[0]
        action = "already_triaged"
        if pr["state"] == "open":
            action = dispatch(api, branch, sha(pr["head"]["sha"]), summary, files)
        return {"action": action, "pr": pr["number"]}
    if sum(bot(pr) and pr.get("state") == "open" and pr.get("head", {}).get("ref", "").startswith(
            "automation/security-") for pr in all_prs) >= 3:
        raise ValueError("Review the three existing security PRs before creating another")
    ref = api.request("GET", f"{BASE}/git/ref/heads/{default_branch}")
    if sha(ref["object"]["sha"]) != summary["base"]:
        raise ValueError("Default branch moved; prepare again, never overwrite newer state")
    existing = optional(api, f"{BASE}/git/ref/heads/{branch}")
    if existing:
        head = sha(existing["object"]["sha"])
        verify_branch(api, summary["base"], head, files)
    else:
        original = api.request("GET", f"{BASE}/git/commits/{summary['base']}")
        entries = []
        for path, content in sorted(files.items()):
            blob = api.request("POST", f"{BASE}/git/blobs", {"content": content, "encoding": "utf-8"})
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": sha(blob["sha"])})
        tree = api.request("POST", f"{BASE}/git/trees", {"base_tree": sha(original["tree"]["sha"]), "tree": entries})
        commit = api.request("POST", f"{BASE}/git/commits", {
            "message": "deps: security maintenance " + identity,
            "tree": sha(tree["sha"]), "parents": [summary["base"]]})
        head = sha(commit["sha"])
        current = api.request("GET", f"{BASE}/git/ref/heads/{default_branch}")
        if sha(current["object"]["sha"]) != summary["base"]:
            raise ValueError("Default branch moved during preparation; no branch is published")
        # No force push and no update of an existing ref, including main.
        api.request("POST", f"{BASE}/git/refs", {"ref": "refs/heads/" + branch, "sha": head})
    target = summary["target"]
    title = (f"deps: {target['package']} {target['from']} to {target['to']}" if summary["decision"] == "patch"
             else "deps: manual review of RustSec findings")
    advisories = sorted({r["advisory"] for r in summary["findings"]})
    body = (f"{marker}\n\nDaily RustSec audit found: {', '.join(advisories)}.\n\n"
            f"Decision: **{summary['decision']}**; reason: `{summary['reason']}`. "
            f"Audit database: `{summary['audit_database']}`.\n\n"
            "A patch proposal changes only the locked package version/checksum and its exact, byte-identical license identity. "
            "A manual draft contains only a report and does not claim to fix the vulnerability.\n\n"
            "Full CI is explicitly requested for this head; GitHub may also show an approval-required PR run. "
            "Review the completed CI, certificate/API compatibility and license evidence before merging. "
            "Merge, release and installation are human actions; installed packages remain unchanged.\n")
    pr = api.request("POST", f"{BASE}/pulls", {"head": branch, "base": default_branch,
                     "title": title, "body": body, "draft": summary["decision"] == "manual"})
    if not bot(pr) or type(pr.get("number")) is not int or pr.get("head", {}).get("sha") != head:
        raise ValueError("Unexpected managed PR response")
    return {"action": dispatch(api, branch, head, summary, files), "pr": pr["number"]}


def main():
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY") != DOWNSTREAM
            or os.environ.get("GITHUB_EVENT_NAME") not in ("schedule", "workflow_dispatch", "push")
            or os.environ.get("DRY_RUN") != "false"
            or os.environ.get("DEPENDENCY_MAINTENANCE_ENABLED") != "true"):
        raise RuntimeError("Publishing requires an explicitly enabled live repository workflow")
    api = GitHubAPI(os.environ["GH_TOKEN"])
    repo = api.request("GET", BASE)
    default = repo["default_branch"]
    if os.environ.get("GITHUB_REF") != "refs/heads/" + default:
        raise RuntimeError("Only the actual default branch may publish dependency proposals")
    data = Path("proposal/proposal.json").read_bytes()
    if len(data) > 3 * 1024 * 1024:
        raise ValueError("Proposal exceeds size limit")
    summary, files = validate(json.loads(data))
    if summary["base"] != os.environ.get("GITHUB_SHA"):
        raise ValueError("Proposal is not from this trusted workflow revision")
    print(json.dumps(publish(api, summary, files, default)))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Dependency PR publication failed; no automatic retry of writes; reconcile on the next run") from None
