#!/usr/bin/env python3
"""Prove active managed streams fail before the listener-timeout fix and survive after it."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TEST = "active_tcp_udp_survive_listener_timeout_and_revoke_remains_scoped"
FIX = """                    if self.context.managed_policy.is_some() {
                        while self.request_tasks.try_join_next().is_some() {}
                        // Existing pipes have their own idle timeouts. Waiting
                        // for a new CONNECT must not terminate those pipes.
                        if !self.request_tasks.is_empty() {
                            continue;
                        }
                    }
"""


def probe():
    return subprocess.run(
        ["cargo", "test", "--locked", "-p", "solartt-agent", "--test", "transport", TEST,
         "--", "--exact", "--nocapture"],
        cwd=ROOT, capture_output=True, text=True, timeout=1800,
    )


def validate_baseline_failure(result):
    ready = "SOLARTT_LISTENER_STREAMS_READY"
    elapsed = "SOLARTT_LISTENER_DEADLINE_ELAPSED"
    lost = "SOLARTT_LISTENER_ORIGINAL_STREAM_LOST:"
    if (result.returncode != 101 or "1 failed" not in result.stdout
            or f"{TEST} ... FAILED" not in result.stdout
            or ready not in result.stdout or elapsed not in result.stdout
            or lost not in result.stderr
            or result.stdout.index(ready) > result.stdout.index(elapsed)):
        raise ValueError("Baseline did not lose established streams after the listener deadline")


def main():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_OS") != "Linux"
            or not str(ROOT).startswith("/home/runner/work/")):
        raise SystemExit("Native regression builds require a disposable GitHub-hosted runner")
    source = ROOT / ".upstream/lib/src/tunnel.rs"
    fixed = source.read_bytes()
    if fixed.decode().count(FIX) != 1:
        raise SystemExit("Listener-timeout fix shape changed; review baseline reconstruction")
    baseline = fixed.decode().replace(FIX, "", 1).encode()
    logs = ROOT / ".dev/listener-timeout-regression"
    logs.mkdir(parents=True, exist_ok=True)
    try:
        source.write_bytes(baseline)
        red = probe()
        (logs / "before.log").write_text(red.stdout + red.stderr)
        try:
            validate_baseline_failure(red)
        except ValueError as error:
            print((red.stdout + red.stderr)[-6000:], flush=True)
            raise SystemExit(str(error)) from None
        print("Previous implementation: active-stream listener timeout reproduced", flush=True)
    finally:
        source.write_bytes(fixed)
    green = probe()
    (logs / "after.log").write_text(green.stdout + green.stderr)
    if green.returncode or "1 passed" not in green.stdout:
        print((green.stdout + green.stderr)[-6000:], flush=True)
        raise SystemExit("Fixed implementation failed active-stream or scoped-revocation acceptance")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    (output / "listener-timeout-regression.json").write_text(json.dumps({
        "status": "PASS", "test": TEST,
        "previous_implementation": "FAIL: active streams lost while waiting for a new CONNECT",
        "fixed_implementation": "PASS: original A/B TCP+UDP streams survive; revoke closes A and preserves B",
        "accelerated_listener_timeout_seconds": 1,
        "production_default_listener_timeout_seconds": 600,
        "quota_modes": ["limited", "unlimited"],
        "auxiliary_health_requests_or_reconnects": False,
        "baseline_failure_phase": "established original streams after listener deadline; fixture tasks running",
        "previous_source_sha256": hashlib.sha256(baseline).hexdigest(),
        "fixed_source_sha256": hashlib.sha256(fixed).hexdigest(),
        "scope": "Isolated real TLS/H2 forwarding on a disposable GitHub runner; no production changes",
    }, indent=2) + "\n")
    print("Fixed implementation: active TCP/UDP and scoped revoke PASS", flush=True)


if __name__ == "__main__":
    main()
