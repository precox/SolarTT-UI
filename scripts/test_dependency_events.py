"""Synthetic read-only Actions metadata and durable Telegram event tests."""
import copy
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from github_api import GitHubAPI, GitHubError
from notify_dependency_events import FAILURE, report, snapshot, validate_snapshot
from notify_trusttunnel_telegram import MonitorError
from scan_dependency_events import (LIVE_RECEIPT, WORKFLOW_URL, audit_snapshot,
                                    LimitedAPI, managed, pr_snapshot, scan)

NOW = datetime(2026, 10, 20, 21, tzinfo=timezone.utc)


def run(number=1, **updates):
    return {"id": number, "run_attempt": 1, "head_branch": "main", "status": "completed",
            "conclusion": "success", "created_at": (NOW - timedelta(hours=number)).isoformat(),
            "event": "schedule", **updates}


def jobs(live=True):
    return [{"name": "prepare", "steps": [{"name": LIVE_RECEIPT, "conclusion": "success",
                                               "completed_at": (NOW - timedelta(minutes=30)).isoformat()}] if live else []}]


def pull(number=12, **updates):
    return {"number": number, "state": "open", "draft": False,
            "user": {"type": "Bot", "id": 41898282, "login": "github-actions[bot]"},
            "head": {"ref": "automation/security-" + "a" * 24, "sha": "a" * 40,
                     "repo": {"full_name": "precox/SolarTT-UI"}}, **updates}


class API:
    def __init__(self):
        self.runs = [run()]
        self.jobs = {(1, 1): jobs()}
        self.prs = []
        self.closed = {}
        self.ci = []

    def pages(self, path):
        return iter(self.prs)

    def request(self, method, path, payload=None):
        assert method == "GET" and payload is None
        if "/attempts/" in path:
            number, tail = path.split("/runs/")[1].split("/attempts/")
            attempt = int(tail.split("/")[0])
            if "/jobs?" in path:
                return {"jobs": self.jobs.get((int(number), attempt), [])}
            return run(int(number), run_attempt=attempt, conclusion="failure")
        if "/workflows/ci.yml/runs?" in path:
            return {"workflow_runs": self.ci}
        if "/runs?" in path:
            return {"workflow_runs": self.runs}
        if "/workflows/" in path:
            return {"state": "active"}
        if "/pulls?" in path:
            return self.prs
        if "/pulls/" in path:
            return self.closed[int(path.rsplit("/", 1)[1])]
        return {"default_branch": "main"}


class ObservationTests(unittest.TestCase):
    def test_closed_backlog_and_new_prs_make_durable_progress_within_api_budget(self):
        backend = API()
        backend.prs = [pull(n, head={**pull()["head"], "sha": f"{n:040x}"}) for n in range(20, 25)]
        backend.closed = {n: pull(n, state="closed") for n in range(10, 15)}
        backend.ci = [{"id": n + 100, "head_sha": f"{n:040x}", "status": "completed",
                       "conclusion": "success", "event": "workflow_dispatch", "run_started_at": NOW.isoformat()}
                      for n in range(20, 25)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.json"
            path.write_text(json.dumps({"version": 1, "audit": {"status": "OK", "notified_at": 100},
                                       "prs": {str(n): {"head": "a" * 40, "state": "open", "draft": False,
                                                        "ci": "success", "notified_at": 100} for n in range(10, 15)}}))
            sent = []
            for tick in range(10):
                state = json.loads(path.read_text())
                tracked = [int(n) for n, pr in state["prs"].items() if pr["state"] == "open"]
                with patch.object(GitHubAPI, "request", side_effect=backend.request) as reads:
                    data = scan(LimitedAPI(), tracked, NOW, cursor=state.get("cursor", 0))
                    self.assertLessEqual(reads.call_count, 12)
                self.assertEqual(data["audit"]["status"], "OK")
                if tick == 0:
                    self.assertTrue(data["deferred"])
                self.assertLessEqual(report(path, data, sent.append, now=200 + tick), 3)
            final = json.loads(path.read_text())
            self.assertTrue(all(final["prs"][str(n)]["state"] == "closed" for n in range(10, 15)))
            self.assertTrue(all(final["prs"][str(n)]["ci"] == "success" for n in range(20, 25)))
            self.assertEqual(len(sent), 15)  # Five closures, five new PRs, five passing CI results.
            self.assertTrue(all(sum(f"PR #{n} закрыт" in text for text in sent) == 1 for n in range(10, 15)))

    def test_ci_cursor_does_not_starve_later_prs_when_audit_uses_more_reads(self):
        backend = API()
        backend.runs = [run(n) for n in range(1, 7)]
        backend.jobs = {(n, 1): jobs(n == 6) for n in range(1, 7)}
        backend.prs = [pull(n, head={**pull()["head"], "sha": f"{n:040x}"}) for n in range(20, 25)]
        queried = set()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.json"
            for tick in range(3):
                cursor = json.loads(path.read_text()).get("cursor", 0) if path.exists() else 0
                with patch.object(GitHubAPI, "request", side_effect=backend.request) as reads:
                    data = scan(LimitedAPI(), (), NOW, cursor=cursor)
                    self.assertLessEqual(reads.call_count, 12)
                    queried.update(call.args[1].split("head_sha=")[1].split("&")[0]
                                   for call in reads.call_args_list if "head_sha=" in call.args[1])
                self.assertTrue(data["deferred"])
                report(path, data, lambda _: None, now=200 + tick)
            self.assertEqual(queried, {f"{n:040x}" for n in range(20, 25)})

    def test_remote_api_failure_is_not_treated_as_deferred_work(self):
        backend = API()
        backend.prs = [pull()]
        def read(method, path, payload=None):
            if "head_sha=" in path:
                raise GitHubError("Synthetic HTTP 503")
            return backend.request(method, path, payload)
        with patch.object(GitHubAPI, "request", side_effect=read), self.assertRaises(GitHubError):
            scan(LimitedAPI(), now=NOW)
        with self.assertRaises(GitHubError):
            scan(backend, now=NOW, cursor=-1)

    def test_dry_runs_and_stale_invocations_cannot_establish_health(self):
        api = API()
        api.jobs[(1, 1)] = jobs(False)
        self.assertEqual(audit_snapshot(api, "main", NOW)["status"], "CRITICAL")
        api.runs = [run(created_at=(NOW - timedelta(days=4)).isoformat())]
        api.jobs[(1, 1)] = jobs()
        self.assertEqual(audit_snapshot(api, "main", NOW)["status"], "CRITICAL")

    def test_unordered_runs_and_reporter_only_retry_do_not_hide_real_failure(self):
        api = API()
        api.runs = [run(3), run(1, run_attempt=2)]
        api.jobs = {(3, 1): jobs(), (1, 2): jobs(False), (1, 1): jobs()}
        result = audit_snapshot(api, "main", NOW)
        self.assertEqual(result["status"], "CRITICAL")
        self.assertTrue(result["url"].endswith("/1/attempts/1"))

    def test_author_fork_and_branch_identity_are_required(self):
        self.assertTrue(managed(pull()))
        for pr in [pull(user={"type": "User", "id": 41898282, "login": "github-actions[bot]"}),
                   pull(head={"ref": "automation/security-" + "a" * 24, "repo": {"full_name": "other/fork"}}),
                   pull(head={"ref": "fix/example", "repo": {"full_name": "precox/SolarTT-UI"}})]:
            self.assertFalse(managed(pr))
        self.assertTrue(managed(pull(user={"type": "Bot", "id": 49699333, "login": "dependabot[bot]"},
                                     head={"ref": "dependabot/github_actions/actions/checkout-123", "repo": {"full_name": "precox/SolarTT-UI"}})))

    def test_old_head_green_ci_and_approval_required_run_are_not_success(self):
        api = API()
        api.ci = [{"id": 99, "head_sha": "b" * 40, "status": "completed", "conclusion": "success",
                   "event": "pull_request", "run_started_at": NOW.isoformat()},
                  {"id": 100, "head_sha": "a" * 40, "status": "completed", "conclusion": "action_required",
                   "event": "pull_request", "run_started_at": NOW.isoformat()}]
        self.assertEqual(pr_snapshot(api, pull())["ci"], "pending")
        api.ci.append({"id": 101, "head_sha": "a" * 40, "status": "completed", "conclusion": "failure",
                       "event": "workflow_dispatch", "run_started_at": NOW.isoformat()})
        self.assertEqual(pr_snapshot(api, pull())["ci"], "failure")

    def test_tracked_closed_pr_is_read_without_scanning_historical_messages(self):
        api = API()
        api.closed[12] = pull(state="closed")
        result = scan(api, [12], NOW)
        self.assertEqual(result["prs"][0]["state"], "closed")

    @patch("notify_dependency_events.subprocess.run")
    def test_child_timeout_invalid_json_and_crash_become_unknown(self, process):
        import subprocess
        for value in [subprocess.CompletedProcess([], 1, b"private output"),
                      subprocess.CompletedProcess([], 0, b"private output")]:
            process.return_value = value
            self.assertEqual(snapshot("", []), FAILURE)
        process.side_effect = subprocess.TimeoutExpired("synthetic", 100)
        self.assertEqual(snapshot("", []), FAILURE)

    @patch("github_api.urllib.request.urlopen")
    def test_shared_client_supports_empty_dispatch_response(self, urlopen):
        response = MagicMock(status=204)
        urlopen.return_value.__enter__.return_value = response
        self.assertIsNone(GitHubAPI().request("POST", "/synthetic/dispatches", {"ref": "example"}))
        response.read.assert_not_called()


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.json"
        self.data = {"audit": {"status": "OK", "reason": "audit_completed", "url": WORKFLOW_URL},
                     "prs": [{"number": 12, "head": "a" * 40, "state": "open", "draft": False,
                              "url": "https://github.com/precox/SolarTT-UI/pull/12", "ci": "success",
                              "ci_url": "https://github.com/precox/SolarTT-UI/actions/runs/123"}]}

    def test_new_pr_ci_dedup_head_update_and_close(self):
        sent = []
        self.assertEqual(report(self.path, self.data, sent.append, now=100), 2)
        self.assertEqual(report(self.path, self.data, sent.append, now=200), 0)
        self.data["prs"][0].update(head="b" * 40, ci="pending", ci_url="")
        self.assertEqual(report(self.path, self.data, sent.append, now=300), 1)
        self.data["prs"][0].update(ci="failure", ci_url="https://github.com/precox/SolarTT-UI/actions/runs/124")
        self.assertEqual(report(self.path, self.data, sent.append, now=400), 1)
        self.data["prs"][0]["state"] = "closed"
        self.assertEqual(report(self.path, self.data, sent.append, now=500), 1)

    def test_delivery_failure_keeps_unacknowledged_ci_for_next_tick(self):
        sent = []
        self.data.update(cursor=12, deferred=True)
        def deliver(text):
            if text.startswith("🟢"):
                raise MonitorError("Synthetic delivery failure")
            sent.append(text)
        with self.assertRaises(MonitorError):
            report(self.path, self.data, deliver, now=100)
        state = json.loads(self.path.read_text())
        self.assertIsNone(state["prs"]["12"]["ci"])
        self.assertNotIn("cursor", state)
        self.assertEqual(report(self.path, self.data, sent.append, now=200), 1)
        self.assertEqual(json.loads(self.path.read_text())["cursor"], 12)
        self.assertEqual(len(sent), 2)

    def test_message_budget_defers_remaining_events_without_losing_them(self):
        self.data["prs"].append({**self.data["prs"][0], "number": 13,
                                 "url": "https://github.com/precox/SolarTT-UI/pull/13"})
        self.data["audit"]["status"] = "CRITICAL"
        sent = []
        self.assertEqual(report(self.path, self.data, sent.append, now=100), 3)
        self.assertEqual(report(self.path, self.data, sent.append, now=200), 2)

    def test_recovery_and_daily_reminder(self):
        self.data["prs"] = []
        self.data["audit"]["status"] = "CRITICAL"
        sent = []
        self.assertEqual(report(self.path, self.data, sent.append, now=100), 1)
        self.assertEqual(report(self.path, self.data, sent.append, now=200), 0)
        self.assertEqual(report(self.path, self.data, sent.append, now=86500), 1)
        self.data["audit"]["status"] = "OK"
        self.assertEqual(report(self.path, self.data, sent.append, now=86600), 1)

    def test_untrusted_urls_and_corrupt_state_never_send_or_reset(self):
        bad = copy.deepcopy(self.data)
        bad["prs"][0]["ci_url"] = "https://private.example/token"
        with self.assertRaises(MonitorError):
            validate_snapshot(bad)
        for fields in ({"cursor": -1}, {"cursor": True}, {"deferred": "true"}):
            with self.assertRaises(MonitorError):
                validate_snapshot({**self.data, **fields})
        self.path.write_text("{")
        sent = MagicMock()
        with self.assertRaises(MonitorError):
            report(self.path, self.data, sent, now=100)
        sent.assert_not_called()
        self.assertEqual(self.path.read_text(), "{")


if __name__ == "__main__":
    unittest.main()
