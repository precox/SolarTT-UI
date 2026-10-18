#!/usr/bin/env python3
"""Maintain one watcher failure issue; never publish logs or change upstream pins."""
import argparse
import json
import os
import re

from github_api import DOWNSTREAM, GitHubAPI, GitHubError

TITLE = "upstream: TrustTunnel release watcher needs attention"
MARKER = "<!-- solartt-upstream-watch:health -->"
# Numeric GitHub.com identity, not user-controlled issue text or a display name.
BOT_USER_ID = 41898282  # https://api.github.com/users/github-actions%5Bbot%5D


def owned_by_actions(issue):
    author = issue.get("user")
    return (isinstance(author, dict) and type(author.get("id")) is int
            and author["id"] == BOT_USER_ID and author.get("type") == "Bot")


def failure_body(run_url):
    return f"""{MARKER}
The TrustTunnel release watcher did not complete successfully. Release discovery is incomplete;
this result does not mean that no new stable releases exist.

Latest failed attempt: {run_url}

Inspect the Actions error, fix the cause and run the watcher on the default
branch with `dry_run=false`. A successful normal run closes this issue;
another failure reopens the same issue. Repeated failures update this body.

This is a monitoring task, not an upstream upgrade or a deployment request.
No production logs, credentials or profiles are attached. Keep investigation
notes in comments: automation owns this body. Preserve the hidden marker.
"""


def report(api, result, run_id, attempt, create=False, *, watch_run_id, watch_attempt):
    if result not in ("success", "failure"):
        raise GitHubError("Health reporting requires a success or failure result")
    if any(not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value)
           for value in (run_id, attempt)):
        raise GitHubError("Invalid workflow run identity")
    if (watch_run_id != run_id or watch_attempt != attempt
            or not isinstance(watch_run_id, str) or not isinstance(watch_attempt, str)):
        raise GitHubError("Watcher did not execute in this run attempt; use Re-run all jobs")
    run_url = f"https://github.com/{DOWNSTREAM}/actions/runs/{run_id}/attempts/{attempt}"
    # Read every page before any write; an API failure is never an empty set.
    issues = [issue for issue in api.pages(f"/repos/{DOWNSTREAM}/issues?state=all")
              if "pull_request" not in issue and owned_by_actions(issue)]
    if any(not isinstance(issue.get("title"), str)
           or issue.get("body") is not None and not isinstance(issue["body"], str)
           for issue in issues):
        raise GitHubError("Invalid issue identity fields in health discovery")
    matches = [issue for issue in issues if issue.get("title") == TITLE
               or MARKER in (issue.get("body") or "").splitlines()]
    if len(matches) > 1:
        raise GitHubError("Multiple watcher health issues found; consolidate them manually")
    issue = matches[0] if matches else None
    if issue and (type(issue.get("number")) is not int or issue["number"] < 1
                  or issue.get("state") not in ("open", "closed")):
        raise GitHubError("Invalid watcher health issue response")
    action, payload = "none", None
    if result == "failure":
        body = failure_body(run_url)
        if not issue:
            action, payload = "create", {"title": TITLE, "body": body}
        elif issue["state"] == "closed":
            action, payload = "reopen", {"state": "open", "body": body}
        elif issue.get("body") != body:
            action, payload = "update", {"body": body}
    elif issue and issue["state"] == "open":
        body = issue.get("body") or ""
        if MARKER not in body.splitlines():
            body = MARKER + "\n" + body
        body += f"\n\nRecovery confirmed by a successful normal watcher attempt: {run_url}\n"
        action, payload = "close", {"state": "closed", "state_reason": "completed", "body": body}
    number = issue["number"] if issue else None
    if create and payload is not None:
        path = f"/repos/{DOWNSTREAM}/issues"
        response = api.request("POST" if action == "create" else "PATCH",
                               path if action == "create" else f"{path}/{number}", payload)
        expected_state = "closed" if action == "close" else "open"
        if (not isinstance(response, dict) or not owned_by_actions(response)
                or type(response.get("number")) is not int
                or response["number"] < 1 or response.get("state") != expected_state
                or number is not None and response["number"] != number):
            raise GitHubError("Invalid health issue write response; rerun to reconcile before retrying")
        number = response["number"]
    return {"result": result, "mode": "create" if create else "dry-run",
            "action": action, "issue": number, "run_url": run_url}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", choices=("success", "failure"), required=True)
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument("--attempt", default=os.environ.get("GITHUB_RUN_ATTEMPT"))
    parser.add_argument("--watch-run-id", default=os.environ.get("WATCH_RUN_ID"))
    parser.add_argument("--watch-attempt", default=os.environ.get("WATCH_ATTEMPT"))
    parser.add_argument("--create-issues", action="store_true", help="apply changes (default is read-only)")
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN")
    if args.create_issues and not token:
        parser.error("--create-issues requires GH_TOKEN with issues:write for " + DOWNSTREAM)
    if args.create_issues and (os.environ.get("GITHUB_ACTIONS") != "true"
                              or os.environ.get("GITHUB_REPOSITORY") != DOWNSTREAM):
        parser.error("Health issue writes require the repository workflow and its built-in GITHUB_TOKEN")
    try:
        print(json.dumps(report(GitHubAPI(token), args.result, args.run_id, args.attempt,
                                create=args.create_issues, watch_run_id=args.watch_run_id,
                                watch_attempt=args.watch_attempt), indent=2))
    except GitHubError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
