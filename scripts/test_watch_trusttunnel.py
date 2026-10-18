"""Watcher regressions use synthetic API responses and never write to GitHub."""
import copy
import http.client
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from watch_trusttunnel import (
    DOWNSTREAM, UPSTREAM, GitHub, WatchError, already_tracked, issue_marker,
    issue_title, stable_releases, stable_version, watch,
)

PIN = {"repository": UPSTREAM, "tag": "v1.1.0", "commit": "a" * 40, "archive_sha256": "b" * 64}


def release(tag, **changes):
    return {"tag_name": tag, "draft": False, "prerelease": False,
            "published_at": "2026-10-17T12:00:00Z", **changes}


class FakeAPI(GitHub):
    """Exercise the real pagination code over an in-memory API."""
    def __init__(self, releases=None, issues=None):
        self.releases = releases if releases is not None else [release("v1.2.0"), release("v1.1.0")]
        self.issues = issues if issues is not None else []
        self.commits = {"v1.1.0": PIN["commit"], "v1.2.0": "c" * 40, "v1.10.0": "d" * 40}
        self.calls = []
        self.writes = []
        self.fail = None

    def request(self, method, path, payload=None):
        self.calls.append((method, path))
        if self.fail and self.fail in path:
            raise WatchError("synthetic API failure")
        if method == "POST":
            self.writes.append(payload)
            issue = {**payload, "number": len(self.issues) + 1, "state": "open"}
            self.issues.append(issue)
            return issue
        if "/commits/" in path:
            return {"sha": self.commits[path.rsplit("/", 1)[1]]}
        page = int(path.rsplit("page=", 1)[1])
        source = self.releases if "/releases?" in path else self.issues
        return copy.deepcopy(source[(page - 1) * 100:page * 100])


class SelectionTests(unittest.TestCase):
    def test_numeric_version_order_and_major_versions(self):
        items = [release(tag) for tag in ["v1.9.0", "v2.0.0", "v1.10.0", "v1.2.10", "v1.2.9"]]
        self.assertEqual([r.canonical for r in stable_releases(items)],
                         ["v2.0.0", "v1.10.0", "v1.9.0", "v1.2.10", "v1.2.9"])
        self.assertEqual(stable_version("0.0.1"), (0, 0, 1))

    def test_prerelease_names_are_excluded_even_if_api_flag_is_false(self):
        for tag in ["v1.3.0-beta.2", "v2.0.0-rc.1", "v2.0.0-RC1", "v2.0.0-alpha",
                    "v2.0.0-preview", "v2.0.0+build", "v01.2.3", "v1.2", "latest", None, "v1.2.3\n"]:
            with self.subTest(tag=tag):
                self.assertIsNone(stable_version(tag))
                self.assertEqual(stable_releases([release(tag)]), [])

    def test_draft_and_prerelease_flags_exclude_plain_stable_tags(self):
        self.assertEqual(stable_releases([release("v2.0.0", draft=True),
                                         release("v3.0.0", prerelease=True)]), [])

    def test_missing_flags_or_timestamp_fail_closed(self):
        for field in ["draft", "prerelease", "published_at"]:
            item = release("v2.0.0")
            del item[field]
            with self.subTest(field=field), self.assertRaises(WatchError):
                stable_releases([item])

    def test_duplicate_release_and_ambiguous_alias(self):
        self.assertEqual(len(stable_releases([release("v1.2.0")] * 2)), 1)
        with self.assertRaises(WatchError):
            stable_releases([release("v1.2.0"), release("1.2.0")])

    def test_selects_all_new_versions_independent_of_api_order(self):
        api = FakeAPI([release("v1.2.0"), release("v1.1.0"), release("v1.10.0"),
                       release("v3.0.0-beta.1"), release("v9.0.0", draft=True)])
        result = watch(api, PIN)
        self.assertEqual([r["version"] for r in result["releases"]], ["v1.2.0", "v1.10.0"])
        self.assertEqual(api.writes, [])

    def test_pin_identity_uses_resolved_tag_not_target_commitish(self):
        api = FakeAPI([release("v1.2.0", target_commitish=PIN["commit"]),
                       release("v1.1.0", target_commitish="main")])
        self.assertEqual(watch(api, PIN)["current"], "v1.1.0")
        api.commits["v1.1.0"] = "f" * 40
        api.commits["v1.2.0"] = PIN["commit"]
        with self.assertRaisesRegex(WatchError, "does not match"):
            watch(api, PIN, create=True)
        self.assertEqual(api.writes, [])

    def test_pinned_tag_must_be_an_exact_published_stable_release(self):
        for pinned in [None, release("v1.1.0", draft=True),
                       release("v1.1.0", prerelease=True), release("1.1.0")]:
            api = FakeAPI([release("v1.2.0")] + ([pinned] if pinned else []))
            api.commits["v1.2.0"] = PIN["commit"]
            with self.subTest(pinned=pinned), self.assertRaisesRegex(WatchError, "not a published stable"):
                watch(api, PIN, create=True)
            self.assertEqual(api.writes, [])

    def test_advance_pinned_tag_when_releases_share_a_commit(self):
        api = FakeAPI([release("v1.10.0"), release("v1.1.0"), release("v1.2.0")])
        api.commits.update({"v1.2.0": PIN["commit"], "v1.10.0": PIN["commit"]})
        result = watch(api, {**PIN, "tag": "v1.2.0"})
        self.assertEqual(result["current"], "v1.2.0")
        self.assertEqual([r["version"] for r in result["releases"]], ["v1.10.0"])
        self.assertEqual(api.writes, [])

    def test_no_new_stable_release_is_a_successful_noop(self):
        api = FakeAPI([release("v1.3.0-beta.2", prerelease=True), release("v1.1.0")])
        self.assertEqual(watch(api, PIN, create=True)["releases"], [])
        self.assertEqual(api.writes, [])

    def test_invalid_pin_or_commit_is_rejected_before_writes(self):
        for changes in [{"repository": "other/repo"}, {"commit": "main"}, {"archive_sha256": "bad"},
                        {"tag": None}, {"tag": "v1.3.0-beta.2"}, {"tag": "main"}]:
            api = FakeAPI()
            with self.subTest(changes=changes), self.assertRaises(WatchError):
                watch(api, {**PIN, **changes}, create=True)
            self.assertEqual(api.calls, [])
        for pin in [{key: value for key, value in PIN.items() if key != "tag"}, None, []]:
            api = FakeAPI()
            with self.subTest(pin=pin), self.assertRaises(WatchError):
                watch(api, pin, create=True)
            self.assertEqual(api.calls, [])
        api = FakeAPI()
        api.commits["v1.2.0"] = "main"
        with self.assertRaises(WatchError):
            watch(api, PIN, create=True)
        self.assertEqual(api.writes, [])

    def test_releases_and_issues_are_paginated_including_closed(self):
        api = FakeAPI([release("v1.3.0-beta.2", prerelease=True)] * 100
                      + [release("v1.2.0"), release("v1.1.0")])
        proposed = stable_releases([release("v1.2.0")])[0]
        api.issues = [{"title": "unrelated", "body": None}] * 100 + [
            {"title": "Edited title", "body": issue_marker(proposed), "state": "closed"}]
        result = watch(api, PIN, create=True)
        self.assertEqual(result["releases"][0]["status"], "tracked")
        self.assertEqual(api.writes, [])
        self.assertIn(("GET", f"/repos/{UPSTREAM}/releases?per_page=100&page=2"), api.calls)
        self.assertIn(("GET", f"/repos/{DOWNSTREAM}/issues?state=all&per_page=100&page=2"), api.calls)


class IdempotencyTests(unittest.TestCase):
    def test_new_release_on_pinned_commit_is_tracked_once(self):
        api = FakeAPI()
        api.commits["v1.2.0"] = PIN["commit"]
        first = watch(api, PIN, create=True)
        self.assertEqual(first["current"], "v1.1.0")
        self.assertEqual([(r["version"], r["status"]) for r in first["releases"]],
                         [("v1.2.0", "created")])
        self.assertEqual(watch(api, PIN, create=True)["releases"][0]["status"], "tracked")
        self.assertEqual(len(api.writes), 1)

    def test_repeated_run_and_closed_issue_do_not_create_duplicates(self):
        api = FakeAPI()
        first = watch(api, PIN, create=True)
        self.assertEqual(first["releases"][0]["status"], "created")
        api.issues[0]["state"] = "closed"
        api.issues[0]["title"] = "Maintainer triaged this version"
        self.assertEqual(watch(api, PIN, create=True)["releases"][0]["status"], "tracked")
        self.assertEqual(len(api.writes), 1)
        body = api.writes[0]["body"]
        for expected in [PIN["commit"], PIN["archive_sha256"], "c" * 40,
                         "upstream/trusttunnel-v1.2.0", "0001-managed-policy.patch", "Riga",
                         "template=upstream-update.md"]:
            self.assertIn(expected, body)

    def test_title_fallback_and_exact_marker_with_pr_exclusion(self):
        proposed = stable_releases([release("v1.2.0")])[0]
        self.assertTrue(already_tracked(proposed, [{"title": issue_title(proposed), "body": None}]))
        self.assertFalse(already_tracked(proposed, [{"title": issue_title(proposed), "pull_request": {}}]))
        self.assertFalse(already_tracked(proposed, [{"body": "quoted " + issue_marker(proposed)}]))
        self.assertFalse(already_tracked(proposed, [{"body": issue_marker(proposed).replace("1.2.0", "1.2.01")}]))

    def test_dry_run_never_writes(self):
        api = FakeAPI()
        self.assertEqual(watch(api, PIN)["releases"][0]["status"], "would-create")
        self.assertEqual(api.writes, [])

    def test_discovery_failures_cannot_create_issues(self):
        for failure in ["/releases", "/commits/", "/issues?state=all"]:
            api = FakeAPI()
            api.fail = failure
            with self.subTest(failure=failure), self.assertRaises(WatchError):
                watch(api, PIN, create=True)
            self.assertEqual(api.writes, [])

    def test_later_candidate_resolution_failure_prevents_all_writes(self):
        api = FakeAPI([release("v1.2.0"), release("v1.1.0"), release("v1.10.0")])
        api.fail = "/commits/v1.10.0"
        with self.assertRaises(WatchError):
            watch(api, PIN, create=True)
        self.assertEqual(api.writes, [])

    def test_later_page_failure_cannot_create_issues(self):
        for endpoint in ["releases", "issues"]:
            api = FakeAPI()
            if endpoint == "releases":
                api.releases = [release("v1.2.0")] * 100
            else:
                api.issues = [{"title": "unrelated"}] * 100
            api.fail = "page=2"
            with self.subTest(endpoint=endpoint), self.assertRaises(WatchError):
                watch(api, PIN, create=True)
            self.assertEqual(api.writes, [])

    def test_rerun_reconciles_an_ambiguous_post_failure(self):
        api = FakeAPI()
        real_request = api.request

        def request(method, path, payload=None):
            result = real_request(method, path, payload)
            if method == "POST":
                raise WatchError("Response lost after successful creation")
            return result

        with patch.object(api, "request", side_effect=request), self.assertRaises(WatchError):
            watch(api, PIN, create=True)
        self.assertEqual(watch(api, PIN, create=True)["releases"][0]["status"], "tracked")
        self.assertEqual(len(api.writes), 1)


class HTTPTests(unittest.TestCase):
    def response(self, value):
        return io.BytesIO(json.dumps(value).encode())

    def http_error(self, code, headers=None):
        return urllib.error.HTTPError("https://api.github.com/test", code, "fixture", headers or {}, None)

    @patch("github_api.time.sleep")
    @patch("github_api.urllib.request.urlopen")
    def test_transient_get_failures_retry_then_succeed(self, urlopen, sleep):
        urlopen.side_effect = [self.http_error(502), urllib.error.URLError("fixture"), self.response([])]
        self.assertEqual(GitHub().request("GET", "/test"), [])
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch("github_api.time.sleep")
    @patch("github_api.urllib.request.urlopen")
    def test_rate_limits_fail_without_early_retry_and_server_retries_are_bounded(self, urlopen, sleep):
        for code, headers, attempts in [(429, {}, 1), (503, {}, 3), (401, {}, 1),
                                         (404, {}, 1), (403, {}, 1),
                                         (403, {"X-RateLimit-Remaining": "0"}, 1),
                                         (403, {"Retry-After": "60"}, 1),
                                         (503, {"Retry-After": "60"}, 1)]:
            urlopen.reset_mock()
            urlopen.side_effect = self.http_error(code, headers)
            with self.subTest(code=code, headers=headers), self.assertRaisesRegex(WatchError, f"HTTP {code}"):
                GitHub().request("GET", "/test")
            self.assertEqual(urlopen.call_count, attempts)

    @patch("github_api.urllib.request.urlopen")
    def test_post_is_never_retried(self, urlopen):
        for error in [self.http_error(503), TimeoutError(), urllib.error.URLError("fixture"),
                      http.client.IncompleteRead(b"partial")]:
            urlopen.reset_mock()
            urlopen.side_effect = error
            with self.subTest(error=type(error)), self.assertRaises(WatchError):
                GitHub().request("POST", "/test", {"body": "fixture"})
            self.assertEqual(urlopen.call_count, 1)

    @patch("github_api.time.sleep")
    @patch("github_api.urllib.request.urlopen")
    def test_interrupted_read_retries_get(self, urlopen, sleep):
        urlopen.side_effect = [http.client.IncompleteRead(b"partial"), self.response([])]
        self.assertEqual(GitHub().request("GET", "/test"), [])
        self.assertEqual(urlopen.call_count, 2)

    @patch("github_api.urllib.request.urlopen")
    def test_malformed_json_and_non_array_page_fail(self, urlopen):
        urlopen.return_value = io.BytesIO(b"not json")
        with self.assertRaisesRegex(WatchError, "invalid JSON"):
            GitHub().request("GET", "/test")
        for value in [{"message": "fixture"}, [None]]:
            urlopen.return_value = self.response(value)
            with self.subTest(value=value), self.assertRaises(WatchError):
                list(GitHub().pages("/test"))

    @patch("github_api.urllib.request.urlopen")
    def test_annotated_tag_commit_resolution_uses_commit_api(self, urlopen):
        urlopen.return_value = self.response({"sha": PIN["commit"]})
        self.assertEqual(GitHub().commit("v1.1.0"), PIN["commit"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, f"https://api.github.com/repos/{UPSTREAM}/commits/v1.1.0")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)


if __name__ == "__main__":
    unittest.main()
