#!/usr/bin/env python3
"""Read-only check for an external monitor: 0 OK, 2 stale/disabled, 3 unknown."""
import json
import os
from datetime import datetime, timedelta, timezone

from github_api import DOWNSTREAM, GitHubAPI, GitHubError

WORKFLOW = "watch-trusttunnel.yml"
RECEIPT = "Record successful normal TrustTunnel check"
MAX_AGE = timedelta(days=10)


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() != timedelta(0):
            raise ValueError()
        return result
    except (AttributeError, TypeError, ValueError):
        raise GitHubError("Invalid Actions UTC timestamp") from None


def collection(api, path, key):
    """These Actions endpoints return objects, unlike the Issues list endpoint."""
    separator = "&" if "?" in path else "?"
    for page in range(1, 1001):
        response = api.request("GET", f"{path}{separator}per_page=100&page={page}")
        items = response.get(key) if isinstance(response, dict) else None
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise GitHubError("Invalid Actions collection")
        yield from items
        if len(items) < 100:
            return
    raise GitHubError("Actions pagination safety limit reached")


def check(api, now=None):
    base = f"/repos/{DOWNSTREAM}"
    repo = api.request("GET", base)
    branch = repo.get("default_branch") if isinstance(repo, dict) else None
    if not isinstance(branch, str) or not branch:
        raise GitHubError("Missing default branch")
    workflow = api.request("GET", f"{base}/actions/workflows/{WORKFLOW}")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("state"), str):
        raise GitHubError("Invalid workflow status")
    if workflow["state"] != "active":
        return {"status": "CRITICAL", "reason": "workflow_not_active", "state": workflow["state"]}
    latest = None
    # Do not stop by run ID or creation date: a full rerun of an old run can
    # perform a genuinely fresh observation. A recent valid witness is enough.
    for run in collection(api, f"{base}/actions/workflows/{WORKFLOW}/runs", "workflow_runs"):
        if (run.get("event") not in ("schedule", "workflow_dispatch")
                or run.get("head_branch") != branch or run.get("status") != "completed"
                or run.get("conclusion") != "success"):
            continue
        run_id, attempt = run.get("id"), run.get("run_attempt")
        if any(type(value) is not int or value < 1 for value in (run_id, attempt)):
            raise GitHubError("Invalid Actions run identity")
        # Pin the attempt. A reporter-only rerun must not reuse the prior watch
        # job's completion time as a new observation.
        path = f"{base}/actions/runs/{run_id}/attempts/{attempt}/jobs"
        for job in collection(api, path, "jobs"):
            if (job.get("name") != "watch" or job.get("status") != "completed"
                    or job.get("conclusion") != "success"):
                continue
            steps = job.get("steps")
            if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
                raise GitHubError("Invalid Actions steps")
            for step in steps:
                if (step.get("name") != RECEIPT or step.get("status") != "completed"
                        or step.get("conclusion") != "success"):
                    continue
                observed = timestamp(step.get("completed_at"))
                current = now or datetime.now(timezone.utc)
                if observed > current:
                    raise GitHubError("Actions observation is in the future; check monitor clock")
                witness = {"observed_at": observed.isoformat(),
                           "run_url": f"https://github.com/{DOWNSTREAM}/actions/runs/{run_id}/attempts/{attempt}"}
                if current - observed <= MAX_AGE:
                    return {"status": "OK", "reason": "recent_successful_normal_check", **witness}
                if latest is None or observed > latest[0]:
                    latest = (observed, witness)
    return {"status": "CRITICAL", "reason": "no_successful_normal_check_within_10_days",
            "last_observed": latest[1] if latest else None}


def main():
    try:
        result = check(GitHubAPI(os.environ.get("GH_TOKEN")))
    except GitHubError as error:
        result = {"status": "UNKNOWN", "reason": str(error)}
    print(json.dumps(result, indent=2))
    raise SystemExit({"OK": 0, "CRITICAL": 2, "UNKNOWN": 3}[result["status"]])


if __name__ == "__main__":
    main()
