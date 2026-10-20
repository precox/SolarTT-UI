#!/usr/bin/env python3
"""Read public dependency audit/PR/CI metadata; never write to GitHub."""
import json
import os
import re
from datetime import datetime, timedelta, timezone

from check_trusttunnel_freshness import timestamp
from github_api import DOWNSTREAM, GitHubAPI, GitHubError

BASE = f"/repos/{DOWNSTREAM}"
LIVE_RECEIPT = "Record live dependency maintenance invocation"
WORKFLOW = "dependency-maintenance.yml"
WORKFLOW_URL = f"https://github.com/{DOWNSTREAM}/actions/workflows/{WORKFLOW}"
BOT_ID, DEPENDABOT_ID = 41898282, 49699333


class LimitedAPI(GitHubAPI):
    def __init__(self, token=None):
        super().__init__(token)
        self.remaining = 12

    def request(self, method, path, payload=None):
        if method != "GET" or self.remaining <= 0:
            raise GitHubError("Read-only observer API budget exceeded")
        self.remaining -= 1
        return super().request(method, path)


def items(api, path, key):
    result = api.request("GET", path)
    values = result.get(key) if isinstance(result, dict) else None
    if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
        raise GitHubError("Invalid Actions collection")
    return values


def audit_snapshot(api, branch, now):
    workflow = api.request("GET", f"{BASE}/actions/workflows/{WORKFLOW}")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("state"), str):
        raise GitHubError("Invalid dependency workflow metadata")
    if workflow.get("state") != "active":
        return {"status": "CRITICAL", "reason": "audit_disabled", "url": WORKFLOW_URL}
    # This observer requires new daily invocations. Re-running a workflow
    # created more than three days ago is not an acceptance/freshness signal.
    cutoff = now - timedelta(days=3)
    runs = items(api, f"{BASE}/actions/workflows/{WORKFLOW}/runs?per_page=100&created=%3E%3D{cutoff.date()}", "workflow_runs")
    if len(runs) >= 100:
        raise GitHubError("Too many recent audit runs; cannot establish latest normal invocation")
    runs = [r for r in runs if r.get("head_branch") == branch
            and r.get("event") in ("schedule", "workflow_dispatch", "push")
            and r.get("status") == "completed" and timestamp(r.get("created_at")) >= cutoff]
    runs.sort(key=lambda r: timestamp(r["created_at"]), reverse=True)
    for run in runs:
        number, attempt = run.get("id"), run.get("run_attempt")
        if type(number) is not int or number < 1 or type(attempt) is not int or not 1 <= attempt <= 1000:
            raise GitHubError("Invalid audit run identity")
        for previous in range(attempt, 0, -1):
            metadata = run if previous == attempt else api.request("GET", f"{BASE}/actions/runs/{number}/attempts/{previous}")
            if metadata.get("id") != number or metadata.get("run_attempt") != previous:
                raise GitHubError("Invalid audit attempt identity")
            if metadata.get("status") != "completed":
                continue
            jobs = items(api, f"{BASE}/actions/runs/{number}/attempts/{previous}/jobs?per_page=100", "jobs")
            if len(jobs) >= 100:
                raise GitHubError("Unexpected audit job count")
            for job in jobs:
                if job.get("name") != "prepare":
                    continue
                steps = job.get("steps")
                if not isinstance(steps, list) or any(not isinstance(s, dict) for s in steps):
                    raise GitHubError("Invalid audit steps")
                for step in steps:
                    if step.get("name") != LIVE_RECEIPT or step.get("conclusion") != "success":
                        continue
                    observed = timestamp(step.get("completed_at"))
                    if observed > now + timedelta(seconds=60):
                        raise GitHubError("Observer clock is behind the audit timestamp")
                    status = "OK" if metadata.get("conclusion") == "success" else "CRITICAL"
                    return {"status": status, "reason": "audit_completed" if status == "OK" else "audit_failed",
                            "url": f"https://github.com/{DOWNSTREAM}/actions/runs/{number}/attempts/{previous}"}
    return {"status": "CRITICAL", "reason": "no_new_live_audit_within_3_days", "url": WORKFLOW_URL}


def managed(pr):
    author, head = pr.get("user", {}), pr.get("head", {})
    branch = head.get("ref", "")
    if (author.get("type") != "Bot" or head.get("repo", {}).get("full_name") != DOWNSTREAM
            or not isinstance(branch, str)):
        return False
    return ((author.get("id") == BOT_ID and author.get("login") == "github-actions[bot]"
             and re.fullmatch(r"automation/security-[0-9a-f]{24}", branch) is not None)
            or (author.get("id") == DEPENDABOT_ID and author.get("login") == "dependabot[bot]"
                and re.fullmatch(r"dependabot/github_actions/[A-Za-z0-9_./-]+", branch) is not None))


def pr_snapshot(api, pr):
    number, head = pr.get("number"), pr.get("head", {}).get("sha")
    if (type(number) is not int or number < 1 or not isinstance(head, str)
            or not re.fullmatch(r"[0-9a-f]{40}", head) or pr.get("state") not in ("open", "closed")
            or type(pr.get("draft")) is not bool):
        raise GitHubError("Invalid managed PR metadata")
    result = {"number": number, "head": head, "state": pr["state"], "draft": pr["draft"],
              "url": f"https://github.com/{DOWNSTREAM}/pull/{number}", "ci": "pending", "ci_url": ""}
    if pr["state"] != "open":
        return result
    runs = items(api, f"{BASE}/actions/workflows/ci.yml/runs?head_sha={head}&per_page=100", "workflow_runs")
    runs = [r for r in runs if r.get("head_sha") == head and r.get("status") == "completed"
            and r.get("conclusion") != "action_required"
            and r.get("event") in ("pull_request", "workflow_dispatch")]
    if runs:
        latest = max(runs, key=lambda r: timestamp(r.get("run_started_at")))
        run_id = latest.get("id")
        if type(run_id) is not int or run_id < 1:
            raise GitHubError("Invalid CI run identity")
        result.update(ci="success" if latest.get("conclusion") == "success" else "failure",
                      ci_url=f"https://github.com/{DOWNSTREAM}/actions/runs/{run_id}")
    return result


def scan(api, tracked=(), now=None):
    now = now or datetime.now(timezone.utc)
    repo = api.request("GET", BASE)
    branch = repo.get("default_branch")
    if not isinstance(branch, str) or not branch:
        raise GitHubError("Missing default branch")
    audit = audit_snapshot(api, branch, now)
    open_prs = list(api.pages(f"{BASE}/pulls?state=open"))
    selected = {pr["number"]: pr for pr in open_prs if managed(pr)}
    if len(selected) > 5:
        raise GitHubError("Too many managed PRs; review the queue")
    for number in tracked:
        if type(number) is not int or number < 1:
            raise GitHubError("Invalid tracked PR number")
        if number not in selected:
            pr = api.request("GET", f"{BASE}/pulls/{number}")
            if managed(pr):
                selected[number] = pr
    return {"audit": audit, "prs": [pr_snapshot(api, pr) for _, pr in sorted(selected.items())]}


def main():
    import sys
    tracked = json.load(sys.stdin).get("tracked", [])
    try:
        result = scan(LimitedAPI(os.environ.get("GH_TOKEN")), tracked)
    except (GitHubError, ValueError, KeyError, TypeError, AttributeError):
        result = {"audit": {"status": "UNKNOWN", "reason": "api_unavailable", "url": WORKFLOW_URL}, "prs": []}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
