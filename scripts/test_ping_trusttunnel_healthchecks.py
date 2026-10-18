"""Heartbeat guards and redaction; synthetic transport, no external pings."""
import io
import unittest
import urllib.error
from unittest.mock import MagicMock

from ping_trusttunnel_healthchecks import (HeartbeatError, MAX_AGE_SECONDS, NoRedirect,
                                          send_ping, validate_observation, validate_url)

URL = "https://hc-ping.com/00000000-0000-4000-8000-000000000000"


class HeartbeatTests(unittest.TestCase):
    def test_only_matching_fresh_normal_observation_is_accepted(self):
        validate_observation("100", "2", "100", "2", "10000", "false", "none", now=10001)
        for values in [("100", "2", "100", "1", "10000", "false", "none"),
                       ("100", "2", "99", "2", "10000", "false", "none"),
                       ("100", "2", "100", "2", None, "false", "none"),
                       ("100", "2", "100", "2", "10000", "true", "none"),
                       ("100", "2", "100", "2", "10000", "false", "recovery"),
                       ("100", "2", "100", "2", "10000", "false", "failure")]:
            with self.subTest(values=values), self.assertRaises(HeartbeatError):
                validate_observation(*values, now=10001)

    def test_delayed_same_attempt_cannot_refresh_ten_day_window(self):
        for now in [10000 + MAX_AGE_SECONDS + 1, 10000 - 31]:
            with self.subTest(now=now), self.assertRaises(HeartbeatError):
                validate_observation("100", "1", "100", "1", "10000", "false", "none", now=now)

    def test_canonical_url_only_prevents_sending_secret_to_other_hosts(self):
        validate_url(URL)
        for url in ["", None, URL.replace("https:", "http:"), URL + "/fail", URL + "?x=1",
                    URL + "#fragment", URL + "\n", " " + URL,
                    URL.replace("hc-ping.com", "hc-ping.com.evil.example"),
                    URL.replace("hc-ping.com", "user@hc-ping.com"),
                    URL.replace("hc-ping.com", "hc-ping.com:444"), "https://hc-ping.com/project/slug"]:
            with self.subTest(url=url), self.assertRaises(HeartbeatError):
                validate_url(url)

    def test_one_empty_post_without_authorization_or_diagnostics(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 200
        opener.open.return_value.__enter__.return_value.read.return_value = b"OK"
        send_ping(URL, opener)
        opener.open.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.data, b"")
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(opener.open.call_args.kwargs, {"timeout": 15})

    def test_wrong_success_body_is_rejected_without_disclosing_it(self):
        for body in [b"OK (not found)", b"OK (rate limited)", b"", b"unexpected private fixture"]:
            opener = MagicMock()
            response = opener.open.return_value.__enter__.return_value
            response.status, response.read.return_value = 200, body
            with self.subTest(body=body), self.assertRaises(HeartbeatError) as error:
                send_ping(URL, opener)
            if body:
                self.assertNotIn(body.decode(), str(error.exception))
            opener.open.assert_called_once()

    def test_network_errors_are_redacted_and_not_retried(self):
        opener = MagicMock()
        for error in [urllib.error.URLError(URL),
                      urllib.error.HTTPError(URL, 302, URL, {}, io.BytesIO(b"fixture")),
                      TimeoutError(URL)]:
            opener.reset_mock()
            opener.open.side_effect = error
            with self.subTest(error=type(error)), self.assertRaises(HeartbeatError) as caught:
                send_ping(URL, opener)
            self.assertNotIn(URL, str(caught.exception))
            opener.open.assert_called_once()

    def test_redirect_cannot_forward_secret(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.org"))


if __name__ == "__main__":
    unittest.main()
