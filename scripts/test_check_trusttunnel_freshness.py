"""External freshness checks using synthetic public Actions responses only."""
import copy
import unittest
from datetime import datetime, timedelta, timezone

from check_trusttunnel_freshness import MAX_AGE, RECEIPT, check
from github_api import GitHubError

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def run(number=1, **changes):
    return {"id": number, "run_attempt": 1, "head_branch": "main", "status": "completed",
            "conclusion": "success", "event": "workflow_dispatch", **changes}


def job(age=timedelta(), **changes):
    return {"name": "watch", "status": "completed", "conclusion": "success", "steps": [
        {"name": RECEIPT, "status": "completed", "conclusion": "success",
         "completed_at": (NOW - age).isoformat()}], **changes}


class API:
    def __init__(self, runs=None, jobs=None, state="active"):
        self.runs = runs or []
        self.jobs = jobs or {}
        self.state = state
        self.calls = []

    def request(self, method, path):
        assert method == "GET"
        self.calls.append(path)
        if "/attempts/" in path:
            number, attempt = path.split("/runs/")[1].split("/attempts/")
            if "/jobs?" not in path:
                return run(int(number), run_attempt=int(attempt))
            values = self.jobs.get((int(number), int(attempt.split("/")[0])), [])
            key = "jobs"
        elif "/runs?" in path:
            values, key = self.runs, "workflow_runs"
        elif "/workflows/" in path:
            return {"state": self.state}
        else:
            return {"default_branch": "main"}
        page = int(path.rsplit("page=", 1)[1])
        return {key: copy.deepcopy(values[(page - 1) * 100:page * 100])}


class FreshnessTests(unittest.TestCase):
    def test_threshold_is_strictly_more_than_ten_days(self):
        for age, status in [(MAX_AGE, "OK"), (MAX_AGE + timedelta(seconds=1), "CRITICAL")]:
            with self.subTest(age=age):
                self.assertEqual(check(API([run()], {(1, 1): [job(age)]}), NOW)["status"], status)

    def test_dry_run_and_test_recovery_have_no_successful_receipt(self):
        for steps in [[], [{"name": RECEIPT, "status": "completed", "conclusion": "skipped"}]]:
            with self.subTest(steps=steps):
                api = API([run()], {(1, 1): [job(steps=steps)]})
                self.assertEqual(check(api, NOW)["status"], "CRITICAL")

    def test_unordered_old_run_full_rerun_is_a_fresh_witness(self):
        api = API([run(100), run(1, run_attempt=3)],
                  {(100, 1): [job(timedelta(days=11))], (1, 3): [job()]})
        result = check(api, NOW)
        self.assertEqual(result["status"], "OK")
        self.assertTrue(result["run_url"].endswith("/1/attempts/3"))

    def test_partial_retry_does_not_refresh_old_watch_observation(self):
        api = API([run(run_attempt=2)], {(1, 1): [job(timedelta(days=11))], (1, 2): [job(timedelta(days=11))]})
        self.assertEqual(check(api, NOW)["status"], "CRITICAL")
        self.assertTrue(any("/attempts/2/jobs" in path for path in api.calls))

    def test_later_failed_or_running_rerun_does_not_erase_prior_success(self):
        for status, conclusion in [("completed", "failure"), ("in_progress", None)]:
            with self.subTest(status=status):
                api = API([run(run_attempt=2, status=status, conclusion=conclusion)],
                          {(1, 1): [job(timedelta(days=1))]})
                result = check(api, NOW)
                self.assertEqual(result["status"], "OK")
                self.assertTrue(result["run_url"].endswith("/1/attempts/1"))

    def test_no_runs_disabled_or_only_unsuccessful_runs_alert(self):
        for api in [API(), API(state="disabled_inactivity"), API([run(conclusion="failure")]),
                    API([run(head_branch="topic")]), API([run(event="pull_request")])]:
            with self.subTest(api=api):
                self.assertEqual(check(api, NOW)["status"], "CRITICAL")

    def test_runs_and_jobs_are_paginated(self):
        api = API([run(i, conclusion="failure") for i in range(1, 101)] + [run(101)],
                  {(101, 1): [{"name": "other"}] * 100 + [job()]})
        self.assertEqual(check(api, NOW)["status"], "OK")
        self.assertEqual(sum(path.endswith("page=2") for path in api.calls), 2)

    def test_invalid_response_or_future_timestamp_is_unknown_not_healthy(self):
        for api in [API([run(id=True)]), API([run()], {(1, 1): [job(steps=None)]}),
                    API([run()], {(1, 1): [job(-timedelta(seconds=1))]})]:
            with self.subTest(api=api), self.assertRaises(GitHubError):
                check(api, NOW)

    def test_api_error_is_not_treated_as_no_runs(self):
        api = API()
        api.request = lambda *args: (_ for _ in ()).throw(GitHubError("Synthetic API error"))
        with self.assertRaises(GitHubError):
            check(api, NOW)


if __name__ == "__main__":
    unittest.main()
