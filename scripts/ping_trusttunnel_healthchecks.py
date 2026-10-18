#!/usr/bin/env python3
"""Send one empty HTTPS success signal after a fresh normal watcher attempt."""
import http.client
import os
import re
import time
import urllib.error
import urllib.request

from github_api import DOWNSTREAM

MAX_AGE_SECONDS = 30 * 60


class HeartbeatError(RuntimeError):
    pass


def validate_observation(run_id, attempt, watch_run_id, watch_attempt, completed_at,
                         dry_run, notification_test, now=None):
    values = (run_id, attempt, watch_run_id, watch_attempt, completed_at)
    if any(not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value) for value in values):
        raise HeartbeatError("Missing or invalid normal watcher observation")
    if run_id != watch_run_id or attempt != watch_attempt:
        raise HeartbeatError("Watcher did not execute in this attempt; start a new normal run")
    if dry_run != "false" or notification_test != "none":
        raise HeartbeatError("Dry runs and notification tests cannot send a heartbeat")
    age = (time.time() if now is None else now) - int(completed_at)
    if age < -30 or age > MAX_AGE_SECONDS:
        raise HeartbeatError("Normal observation is stale or clock is incorrect; start a new normal run")


def validate_url(url):
    # A check UUID can only signal this one check. No management/project API key.
    if (not isinstance(url, str) or not re.fullmatch(
            r"https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", url)):
        raise HeartbeatError("Configure the canonical HTTPS UUID ping URL in the repository secret")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def send_ping(url, opener=None):
    validate_url(url)
    request = urllib.request.Request(url, data=b"", method="POST", headers={
        "User-Agent": "SolarTT-UI-upstream-heartbeat"})
    try:
        client = opener or urllib.request.build_opener(NoRedirect())
        with client.open(request, timeout=15) as response:
            # UUID endpoints may return HTTP 200 for an unknown/rate-limited
            # check. Require the documented success body, never print it.
            if response.status != 200 or response.read(64).strip() != b"OK":
                raise HeartbeatError("Healthchecks did not confirm the success signal")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, http.client.HTTPException):
        # urllib errors/redirects can contain the secret URL. No raw exceptions,
        # response bodies, environments or request headers enter Actions logs.
        raise HeartbeatError("Healthchecks delivery failed; inspect service status and secret configuration") from None


def main():
    env = os.environ
    branch = env.get("DEFAULT_BRANCH")
    if (env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_REPOSITORY") != DOWNSTREAM
            or env.get("GITHUB_EVENT_NAME") not in ("schedule", "workflow_dispatch")
            or not branch or env.get("GITHUB_REF") != "refs/heads/" + branch):
        raise SystemExit("Heartbeat delivery requires the default-branch repository workflow")
    try:
        validate_observation(env.get("GITHUB_RUN_ID"), env.get("GITHUB_RUN_ATTEMPT"),
            env.get("WATCH_RUN_ID"), env.get("WATCH_ATTEMPT"), env.get("NORMAL_COMPLETED_AT"),
            env.get("DRY_RUN"), env.get("NOTIFICATION_TEST"))
        send_ping(env.get("HEALTHCHECKS_TRUSTTUNNEL_PING_URL", ""))
    except HeartbeatError as error:
        raise SystemExit(str(error)) from None
    print("Healthchecks confirmed a fresh normal watcher heartbeat; no diagnostic data sent")


if __name__ == "__main__":
    main()
