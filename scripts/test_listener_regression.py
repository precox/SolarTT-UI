"""Baseline failure attribution; synthetic process results, no builds or sockets."""
import subprocess
import unittest

from check_managed_listener_timeout import TEST, validate_baseline_failure


class ListenerBaselineAttribution(unittest.TestCase):
    def result(self, stdout=None, stderr=None, returncode=101):
        if stdout is None:
            stdout = ("SOLARTT_LISTENER_STREAMS_READY\n"
                      "SOLARTT_LISTENER_DEADLINE_ELAPSED\n"
                      f"test {TEST} ... FAILED\n1 failed\n")
        if stderr is None:
            stderr = "SOLARTT_LISTENER_ORIGINAL_STREAM_LOST: original stream closed\n"
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def test_established_stream_loss_after_deadline_is_accepted(self):
        validate_baseline_failure(self.result())

    def test_fixture_and_build_failures_do_not_prove_timeout(self):
        for message in ["Address already in use", "Fixture echo server stopped",
                        "Fixture endpoint stopped", "compiler error"]:
            with self.subTest(message=message), self.assertRaises(ValueError):
                validate_baseline_failure(self.result(stderr=message))
        for code in [0, 1, -9]:
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate_baseline_failure(self.result(returncode=code))

    def test_setup_and_out_of_order_phases_are_rejected(self):
        valid = self.result()
        for marker in ["SOLARTT_LISTENER_STREAMS_READY", "SOLARTT_LISTENER_DEADLINE_ELAPSED"]:
            with self.subTest(missing=marker), self.assertRaises(ValueError):
                validate_baseline_failure(self.result(stdout=valid.stdout.replace(marker, "")))
        reversed_phases = valid.stdout.replace("STREAMS_READY", "PLACEHOLDER").replace(
            "DEADLINE_ELAPSED", "STREAMS_READY").replace("PLACEHOLDER", "DEADLINE_ELAPSED")
        with self.assertRaises(ValueError):
            validate_baseline_failure(self.result(stdout=reversed_phases))

    def test_another_test_or_empty_selection_is_rejected(self):
        valid = self.result()
        for output in [valid.stdout.replace(TEST, "different_test"),
                       valid.stdout.replace("1 failed", "0 failed")]:
            with self.subTest(output=output), self.assertRaises(ValueError):
                validate_baseline_failure(self.result(stdout=output))


if __name__ == "__main__":
    unittest.main()
