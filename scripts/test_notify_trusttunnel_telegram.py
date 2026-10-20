"""Synthetic transport/state tests: no Telegram messages or server access."""
import fcntl
import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from notify_trusttunnel_telegram import (MonitorError, NoRedirect, REMINDER_SECONDS,
                                        credentials, main, message, report, run_check, send_message)

OK = {"status": "OK", "reason": "recent_successful_normal_check"}
STALE = {"status": "CRITICAL", "reason": "no_successful_normal_check_within_10_days"}
UNKNOWN = {"status": "UNKNOWN", "reason": "checker_timeout"}


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.json"

    def test_initial_healthy_is_quiet_incident_deduplicates_and_recovers(self):
        sent = []
        self.assertFalse(report(self.path, OK, sent.append, now=100))
        self.assertTrue(report(self.path, STALE, sent.append, now=200))
        self.assertFalse(report(self.path, STALE, sent.append, now=300))
        self.assertTrue(report(self.path, OK, sent.append, now=400))
        self.assertFalse(report(self.path, OK, sent.append, now=500))
        self.assertEqual(len(sent), 2)
        self.assertIn("восстановились", sent[-1])

    def test_unknown_is_distinct_incident_and_reminder_is_durable(self):
        sent = []
        report(self.path, STALE, sent.append, now=100)
        report(self.path, UNKNOWN, sent.append, now=200)
        self.assertFalse(report(self.path, UNKNOWN, sent.append, now=201))
        self.assertTrue(report(self.path, UNKNOWN, sent.append, now=200 + REMINDER_SECONDS))
        self.assertEqual(len(sent), 3)

    def test_delivery_failure_does_not_acknowledge_transition_or_recovery(self):
        sent = []
        fail = MagicMock(side_effect=MonitorError("Synthetic delivery failure"))
        for result, stamp in [(STALE, 100), (OK, 200)]:
            before = self.path.read_bytes() if self.path.exists() else None
            with self.assertRaises(MonitorError):
                report(self.path, result, fail, now=stamp)
            self.assertEqual(self.path.read_bytes() if self.path.exists() else None, before)
            self.assertTrue(report(self.path, result, sent.append, now=stamp + 1))
        self.assertEqual(len(sent), 2)

    def test_corrupt_or_future_state_is_not_silently_reset(self):
        sent = MagicMock()
        for raw in ["{", json.dumps({"version": 1, "acknowledged": None, "notified_at": 1000})]:
            self.path.write_text(raw)
            with self.assertRaises(MonitorError):
                report(self.path, STALE, sent, now=100)
            self.assertEqual(self.path.read_text(), raw)
        sent.assert_not_called()

    def test_test_cycle_state_is_separate_and_messages_marked(self):
        report(self.path, OK, lambda _: self.fail("Healthy initial state sends nothing"), now=100)
        before = self.path.read_bytes()
        sent = []
        test_path = Path(self.temp.name) / "test-state.json"
        for result in (STALE, UNKNOWN, OK):
            report(test_path, result, sent.append, now=200, prefix="[TEST] ")
        self.assertEqual(len(sent), 3)
        self.assertTrue(all(text.startswith("[TEST] ") for text in sent))
        self.assertEqual(self.path.read_bytes(), before)

    def test_only_public_evidence_is_forwarded(self):
        text = message({"status": "UNKNOWN", "reason": "private-error-value",
                        "last_observed": {"observed_at": "private-time-value",
                                          "run_url": "https://private.example/value"}})
        self.assertNotIn("private", text)
        text = message({**OK, "observed_at": "2026-10-20T12:00:00+00:00",
                        "run_url": "https://github.com/precox/SolarTT-UI/actions/runs/123/attempts/1"})
        self.assertIn("/123/attempts/1", text)

    def test_credentials_are_file_based_with_optional_empty_github_token(self):
        directory = Path(self.temp.name)
        token = "123456" + ":" + "synthetic" * 4
        (directory / "telegram_token").write_text(token)
        (directory / "telegram_chat_id").write_text("-123")
        (directory / "github_token").write_text("")
        with patch.dict("os.environ", {"CREDENTIALS_DIRECTORY": str(directory),
                                       "TELEGRAM_MESSAGE_THREAD_ID": ""}):
            self.assertEqual(credentials(), (token, "-123", "", None))
            (directory / "telegram_chat_id").write_text("@wrong-destination")
            with self.assertRaises(MonitorError):
                credentials()

    def test_concurrent_invocation_does_not_check_or_send(self):
        with (Path(self.temp.name) / "monitor.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch("sys.argv", ["monitor"]), patch.dict(
                    "os.environ", {"STATE_DIRECTORY": self.temp.name}), patch(
                    "notify_trusttunnel_telegram.credentials", return_value=("", "", "", None)), patch(
                    "notify_trusttunnel_telegram.run_check") as check:
                with self.assertRaises(MonitorError):
                    main()
                check.assert_not_called()

    @patch("notify_trusttunnel_telegram.subprocess.run")
    def test_checker_timeout_crash_and_mismatched_status_are_unknown(self, child):
        child.side_effect = subprocess.TimeoutExpired("synthetic checker", 180)
        self.assertEqual(run_check("")["reason"], "checker_timeout")
        child.side_effect = None
        for code, output in [(0, b"private crash output"), (1, b'{"status":"OK"}'),
                             (0, b'{"status":"UNKNOWN"}'), (0, b"[]")]:
            child.return_value = subprocess.CompletedProcess([], code, output, b"private stderr")
            self.assertEqual(run_check("")["status"], "UNKNOWN")
        child.return_value = subprocess.CompletedProcess([], 0, json.dumps(OK).encode(), b"")
        self.assertEqual(run_check(""), OK)
        self.assertEqual(child.call_args.kwargs["timeout"], 180)

    @patch("notify_trusttunnel_telegram.urllib.request.build_opener")
    def test_telegram_success_requires_matching_chat_and_preserves_topic(self, opener):
        response = MagicMock(status=200)
        response.read.return_value = b'{"ok":true,"result":{"message_id":4,"chat":{"id":-123}}}'
        transport = opener.return_value
        transport.open.return_value.__enter__.return_value = response
        send_message("synthetic-token", "-123", "[TEST] example", topic=42)
        request = transport.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data)["message_thread_id"], 42)
        self.assertNotIn("Authorization", request.headers)
        transport.open.assert_called_once()
        for data in [b'{"ok":false}', b'{"ok":true,"result":{"message_id":4,"chat":{"id":-456}}}',
                     b"[]", b"x" * 65537]:
            response.read.return_value = data
            with self.assertRaises(MonitorError):
                send_message("synthetic-token", "-123", "example")

    @patch("notify_trusttunnel_telegram.urllib.request.build_opener")
    def test_url_bearing_network_errors_are_redacted_and_not_retried(self, opener):
        private = "https://api.telegram.org/botSYNTHETIC_PRIVATE_VALUE/sendMessage"
        opener.return_value.open.side_effect = urllib.error.HTTPError(private, 429, private, {}, None)
        with self.assertRaises(MonitorError) as error:
            send_message("synthetic-token", "-123", "example")
        self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", str(error.exception))
        self.assertNotIn(private, str(error.exception))
        opener.return_value.open.assert_called_once()
        with self.assertRaises(MonitorError):
            NoRedirect().redirect_request(None, None, 302, "", {}, private)


if __name__ == "__main__":
    unittest.main()
