"""Synthetic health issue lifecycle; no GitHub mutations or production state."""
import copy
import http.client
import json
import unittest
import urllib.error
from unittest.mock import patch

from github_api import DOWNSTREAM, GitHubAPI, GitHubError
from report_trusttunnel_health import BOT_USER_ID, MARKER, TITLE, TEST_MARKER, TEST_TITLE, report


BOT = {"id": BOT_USER_ID, "login": "github-actions[bot]", "type": "Bot"}


def fresh_report(api, result, run_id, attempt, create=False, *, notification_test=False):
    """Lifecycle fixtures model a watcher that actually ran in this attempt."""
    return report(api, result, run_id, attempt, create=create,
                  watch_run_id=run_id, watch_attempt=attempt, notification_test=notification_test)


class FakeAPI(GitHubAPI):
    def __init__(self, issues=None):
        self.issues = copy.deepcopy(issues or [])
        self.calls = []
        self.writes = []
        self.fail = None

    def request(self, method, path, payload=None):
        self.calls.append((method, path))
        if self.fail and self.fail in path:
            raise GitHubError("Synthetic API failure")
        if method == "GET":
            page = int(path.rsplit("page=", 1)[1])
            return copy.deepcopy(self.issues[(page - 1) * 100:page * 100])
        self.writes.append((method, path, copy.deepcopy(payload)))
        if method == "POST":
            issue = {**payload, "number": len(self.issues) + 1, "state": "open", "user": copy.deepcopy(BOT)}
            self.issues.append(issue)
        else:
            issue = next(i for i in self.issues if str(i.get("number")) == path.rsplit("/", 1)[1])
            issue.update(payload)
        return copy.deepcopy(issue)


def health_issue(state="open", **changes):
    return {"number": 7, "title": TITLE, "body": MARKER, "state": state, "user": copy.deepcopy(BOT), **changes}


class HealthTests(unittest.TestCase):
    def test_notification_lifecycle_preserves_real_incident_and_reuses_one_test_issue(self):
        real_issue = health_issue(body=MARKER + "\nReal incident evidence")
        api = FakeAPI([real_issue])
        plan = fresh_report(api, "failure", "100", "1", create=True, notification_test=True)
        number = plan["issue"]
        self.assertTrue(plan["notification_test"])
        self.assertEqual(plan["action"], "create")
        self.assertEqual(api.issues[1]["title"], TEST_TITLE)
        self.assertIn("TEST ONLY", api.issues[1]["body"])
        self.assertIn(TEST_MARKER, api.issues[1]["body"].splitlines())
        self.assertNotIn(MARKER, api.issues[1]["body"])
        for result, run, action in [("failure", "100", "none"), ("failure", "101", "update"),
                                    ("success", "102", "close"), ("failure", "103", "reopen"),
                                    ("success", "104", "close"), ("success", "105", "none")]:
            with self.subTest(result=result, run=run):
                plan = fresh_report(api, result, run, "1", create=True, notification_test=True)
                self.assertEqual((plan["action"], plan["issue"]), (action, number))
                self.assertEqual(api.issues[0], real_issue)
                self.assertEqual(len(api.issues), 2)
        self.assertEqual(api.issues[1]["state"], "closed")
        self.assertIn("TEST ONLY: notification test recovery", api.issues[1]["body"])
        self.assertNotIn("successful normal watcher", api.issues[1]["body"])
        self.assertEqual([w[0] for w in api.writes], ["POST", "PATCH", "PATCH", "PATCH", "PATCH"])

    def test_normal_failure_and_recovery_ignore_test_issue(self):
        test_issue = health_issue(title=TEST_TITLE, body=TEST_MARKER)
        for result, expected in [("success", "none"), ("failure", "create")]:
            api = FakeAPI([test_issue])
            with self.subTest(result=result):
                plan = fresh_report(api, result, "100", "1", create=True)
                self.assertFalse(plan["notification_test"])
                self.assertEqual(plan["action"], expected)
                self.assertEqual(api.issues[0], test_issue)
                if result == "failure":
                    self.assertEqual(api.issues[1]["title"], TITLE)
                    self.assertNotIn(TEST_MARKER, api.issues[1]["body"])

    def test_opposite_marker_overrides_title_fallback_in_both_modes(self):
        for test_mode, title, marker in [(True, TEST_TITLE, MARKER), (False, TITLE, TEST_MARKER)]:
            issue = health_issue(title=title, body=marker)
            api = FakeAPI([issue])
            with self.subTest(test_mode=test_mode):
                plan = fresh_report(api, "success", "100", "1", create=True,
                                    notification_test=test_mode)
                self.assertEqual(plan["action"], "none")
                self.assertEqual(api.issues, [issue])

    def test_closed_test_issue_on_later_page_is_reopened(self):
        issue = health_issue("closed", title=TEST_TITLE, body=TEST_MARKER)
        api = FakeAPI([{"title": "unrelated", "body": None}] * 100 + [issue])
        plan = fresh_report(api, "failure", "100", "1", create=True, notification_test=True)
        self.assertEqual((plan["action"], plan["issue"]), ("reopen", 7))
        self.assertEqual(len(api.issues), 101)

    def test_test_mode_keeps_stale_attempt_and_ownership_guards(self):
        external = health_issue(title=TEST_TITLE, body=TEST_MARKER,
                                user={"id": 123, "type": "User"})
        api = FakeAPI([external])
        with self.assertRaisesRegex(GitHubError, "Re-run all jobs"):
            report(api, "failure", "100", "2", create=True, watch_run_id="100",
                   watch_attempt="1", notification_test=True)
        self.assertEqual(api.calls, [])
        plan = fresh_report(api, "success", "100", "2", create=True, notification_test=True)
        self.assertEqual(plan["action"], "none")
        self.assertEqual(api.writes, [])
        plan = fresh_report(api, "failure", "100", "2", create=True, notification_test=True)
        self.assertEqual(plan["action"], "create")
        self.assertEqual(api.issues[0], external)

    def test_test_mode_dry_run_does_not_write(self):
        for result in ["success", "failure"]:
            issue = health_issue(title=TEST_TITLE, body=TEST_MARKER)
            api = FakeAPI([issue])
            with self.subTest(result=result):
                plan = fresh_report(api, result, "100", "1", notification_test=True)
                self.assertEqual(plan["mode"], "dry-run")
                self.assertEqual(api.writes, [])
                self.assertEqual(api.issues, [issue])

    def test_reporter_only_retry_cannot_close_newer_incident(self):
        api = FakeAPI()
        fresh_report(api, "failure", "101", "1", create=True)
        before = copy.deepcopy(api.issues)
        api.calls.clear()
        with self.assertRaisesRegex(GitHubError, "Re-run all jobs"):
            report(api, "success", "100", "2", create=True, watch_run_id="100", watch_attempt="1")
        self.assertEqual(api.calls, [])
        self.assertEqual(api.issues, before)
        self.assertEqual(api.issues[0]["state"], "open")

    def test_reporter_only_retry_cannot_create_false_incident_after_recovery(self):
        api = FakeAPI()
        fresh_report(api, "success", "101", "1", create=True)
        api.calls.clear()
        with self.assertRaisesRegex(GitHubError, "Re-run all jobs"):
            report(api, "failure", "100", "2", create=True, watch_run_id="100", watch_attempt="1")
        self.assertEqual(api.calls, [])
        self.assertEqual(api.issues, [])

    def test_full_rerun_of_older_run_can_recover_with_a_fresh_watch_job(self):
        api = FakeAPI()
        fresh_report(api, "failure", "101", "1", create=True)
        result = report(api, "success", "100", "2", create=True,
                        watch_run_id="100", watch_attempt="2")
        self.assertEqual(result["action"], "close")
        self.assertEqual(api.issues[0]["state"], "closed")

    def test_missing_or_mismatched_provenance_never_accesses_api(self):
        for observed_run, observed_attempt in [(None, None), ("100", None),
                                                (None, "1"), ("99", "1"), ("100", "2")]:
            for result in ["success", "failure"]:
                api = FakeAPI()
                with self.subTest(result=result, run=observed_run, attempt=observed_attempt):
                    with self.assertRaisesRegex(GitHubError, "Re-run all jobs"):
                        report(api, result, "100", "1", create=True,
                               watch_run_id=observed_run, watch_attempt=observed_attempt)
                    self.assertEqual(api.calls, [])

    def test_external_issue_with_copied_marker_is_not_mutated(self):
        issue = health_issue(number=42, title="External bug report", body="```\n" + MARKER + "\n```",
                             user={"id": 123, "login": "external-reporter", "type": "User"})
        api = FakeAPI([issue])
        self.assertEqual(fresh_report(api, "success", "100", "1", create=True)["action"], "none")
        self.assertEqual(api.issues, [issue])
        self.assertEqual(api.writes, [])

    def test_untrusted_copies_do_not_block_owned_issue_or_lose_user_content(self):
        for user in [{"id": 123, "login": "external-reporter", "type": "User"},
                     {"id": 321, "login": "other[bot]", "type": "Bot"}, None, {},
                     {"id": str(BOT_USER_ID), "type": "Bot"},
                     {"id": BOT_USER_ID, "type": "User"}]:
            for result in ["success", "failure"]:
                external = health_issue(number=42, user=user, body="```\n" + MARKER + "\n```")
                api = FakeAPI([external, health_issue()])
                with self.subTest(user=user, result=result):
                    plan = fresh_report(api, result, "100", "1", create=True)
                    self.assertEqual(plan["issue"], 7)
                    self.assertEqual(api.issues[0], external)
                    self.assertEqual(api.writes[0][1], f"/repos/{DOWNSTREAM}/issues/7")

    def test_failure_with_only_an_external_copy_creates_an_owned_issue(self):
        external = health_issue(number=42, user={"id": 123, "type": "User"})
        api = FakeAPI([external])
        plan = fresh_report(api, "failure", "100", "1", create=True)
        self.assertEqual(plan["action"], "create")
        self.assertEqual(api.issues[0], external)
        self.assertEqual(api.issues[1]["user"], BOT)

    def test_wrong_author_in_write_response_is_rejected_without_retry(self):
        api = FakeAPI()
        original = api.request

        def request(method, path, payload=None):
            response = original(method, path, payload)
            if method != "GET":
                response["user"] = {"id": 123, "type": "User"}
            return response

        with patch.object(api, "request", side_effect=request), self.assertRaises(GitHubError):
            fresh_report(api, "failure", "100", "1", create=True)
        self.assertEqual(len(api.writes), 1)

    def test_healthy_without_incident_never_creates_issue(self):
        api = FakeAPI()
        self.assertEqual(fresh_report(api, "success", "100", "1", create=True)["action"], "none")
        self.assertEqual(api.writes, [])

    def test_failure_creates_one_issue_with_safe_attempt_link(self):
        api = FakeAPI()
        first = fresh_report(api, "failure", "100", "2", create=True)
        self.assertEqual(first["action"], "create")
        self.assertEqual(len(api.issues), 1)
        self.assertIn(f"https://github.com/{DOWNSTREAM}/actions/runs/100/attempts/2", api.issues[0]["body"])
        self.assertIn(MARKER, api.issues[0]["body"].splitlines())
        self.assertEqual(fresh_report(api, "failure", "100", "2", create=True)["action"], "none")
        self.assertEqual(len(api.writes), 1)

    def test_failure_updates_open_issue_then_success_closes_and_failure_reopens(self):
        api = FakeAPI()
        fresh_report(api, "failure", "100", "1", create=True)
        number = api.issues[0]["number"]
        self.assertEqual(fresh_report(api, "failure", "101", "1", create=True)["action"], "update")
        failure = api.issues[0]["body"]
        self.assertIn("/runs/101/attempts/1", failure)
        self.assertEqual(fresh_report(api, "success", "102", "1", create=True)["action"], "close")
        self.assertEqual(api.issues[0]["state"], "closed")
        self.assertTrue(api.issues[0]["body"].startswith(failure))
        self.assertIn("/runs/102/attempts/1", api.issues[0]["body"])
        self.assertEqual(fresh_report(api, "success", "103", "1", create=True)["action"], "none")
        self.assertEqual(fresh_report(api, "failure", "104", "1", create=True)["action"], "reopen")
        self.assertEqual(api.issues[0]["state"], "open")
        self.assertEqual(api.issues[0]["number"], number)
        self.assertEqual(len(api.issues), 1)
        self.assertEqual([w[0] for w in api.writes], ["POST", "PATCH", "PATCH", "PATCH"])

    def test_edited_title_marker_and_title_fallback_preserve_identity(self):
        for changes in [{"title": "Investigating"}, {"body": None}]:
            api = FakeAPI([health_issue(**changes)])
            with self.subTest(changes=changes):
                self.assertEqual(fresh_report(api, "failure", "100", "1", create=True)["issue"], 7)
                self.assertEqual(len(api.issues), 1)
                self.assertEqual(api.writes[0][0], "PATCH")
                self.assertIn(MARKER, api.issues[0]["body"].splitlines())

    def test_prs_and_release_tasks_are_not_health_issues(self):
        api = FakeAPI([health_issue(pull_request={}),
                       {"number": 8, "state": "open", "title": "upstream: review TrustTunnel v1.2.0",
                        "body": "<!-- solartt-upstream-watch:TrustTunnel/TrustTunnel:v1.2.0 -->"}])
        self.assertEqual(fresh_report(api, "failure", "100", "1", create=True)["action"], "create")
        self.assertEqual(len(api.issues), 3)
        self.assertEqual(api.issues[0]["body"], MARKER)

    def test_closed_health_issue_on_later_page_is_reused(self):
        api = FakeAPI([{"title": "unrelated", "body": None}] * 100 + [health_issue("closed")])
        self.assertEqual(fresh_report(api, "failure", "100", "1", create=True)["action"], "reopen")
        self.assertEqual(api.writes[0][1], f"/repos/{DOWNSTREAM}/issues/7")
        self.assertIn(("GET", f"/repos/{DOWNSTREAM}/issues?state=all&per_page=100&page=2"), api.calls)

    def test_dry_run_never_mutates_failure_or_recovery(self):
        for result, issues, action in [("failure", [], "create"),
                                       ("failure", [health_issue("closed")], "reopen"),
                                       ("success", [health_issue()], "close")]:
            api = FakeAPI(issues)
            before = copy.deepcopy(api.issues)
            with self.subTest(result=result, action=action):
                plan = fresh_report(api, result, "100", "1")
                self.assertEqual(plan["action"], action)
                self.assertEqual(plan["mode"], "dry-run")
                self.assertEqual(api.writes, [])
                self.assertEqual(api.issues, before)

    def test_invalid_run_identity_or_result_fails_before_api_access(self):
        for result, run, attempt in [("cancelled", "100", "1"), ("skipped", "100", "1"),
                                      ("failure", "../100", "1"), ("success", "0", "1"),
                                      ("failure", "100", "0"), ("failure", "100", None)]:
            api = FakeAPI()
            with self.subTest(result=result, run=run, attempt=attempt), self.assertRaises(GitHubError):
                fresh_report(api, result, run, attempt, create=True)
            self.assertEqual(api.calls, [])

    def test_duplicate_or_malformed_health_issues_fail_before_mutation(self):
        for issues in [[health_issue(), health_issue("closed", number=8)],
                       [health_issue(number=True)], [health_issue(state="unknown")],
                       [health_issue(body=[])], [health_issue(title=None)]]:
            api = FakeAPI(issues)
            with self.subTest(issues=issues), self.assertRaises(GitHubError):
                fresh_report(api, "failure", "100", "1", create=True)
            self.assertEqual(api.writes, [])

    def test_failed_deduplication_page_prevents_issue_creation(self):
        api = FakeAPI([{"title": "unrelated", "body": None}] * 100)
        api.fail = "page=2"
        with self.assertRaises(GitHubError):
            fresh_report(api, "failure", "100", "1", create=True)
        self.assertEqual(api.writes, [])

    def test_ambiguous_post_or_patch_failure_is_reconciled_next_run(self):
        for issues, result, expected in [([], "failure", "none"),
                                         ([health_issue("closed")], "failure", "none"),
                                         ([health_issue()], "success", "none")]:
            api = FakeAPI(issues)
            real = api.request

            def request(method, path, payload=None):
                response = real(method, path, payload)
                if method != "GET":
                    raise GitHubError("Lost response after successful write")
                return response

            with self.subTest(result=result, issues=issues):
                with patch.object(api, "request", side_effect=request), self.assertRaises(GitHubError):
                    fresh_report(api, result, "100", "1", create=True)
                writes = len(api.writes)
                self.assertEqual(fresh_report(api, result, "100", "1", create=True)["action"], expected)
                self.assertEqual(len(api.writes), writes)
                self.assertEqual(len(api.issues), 1)

    def test_bad_write_response_fails_without_blind_retry(self):
        api = FakeAPI()
        original = api.request

        def request(method, path, payload=None):
            response = original(method, path, payload)
            return {} if method != "GET" else response

        with patch.object(api, "request", side_effect=request), self.assertRaises(GitHubError):
            fresh_report(api, "failure", "100", "1", create=True)
        self.assertEqual(len(api.writes), 1)
        self.assertEqual(fresh_report(api, "failure", "100", "1", create=True)["action"], "none")

    @patch("github_api.urllib.request.urlopen")
    def test_patch_requests_are_json_and_never_retried(self, urlopen):
        for error in [urllib.error.HTTPError("https://api.github.com/test", 503, "fixture", {}, None),
                      http.client.IncompleteRead(b"partial")]:
            urlopen.reset_mock()
            urlopen.side_effect = error
            with self.subTest(error=type(error)), self.assertRaises(GitHubError):
                GitHubAPI().request("PATCH", "/test", {"state": "closed"})
            self.assertEqual(urlopen.call_count, 1)
            request = urlopen.call_args.args[0]
            self.assertEqual(request.method, "PATCH")
            self.assertEqual(json.loads(request.data), {"state": "closed"})


if __name__ == "__main__":
    unittest.main()
