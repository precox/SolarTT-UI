#!/usr/bin/env python3
"""Prove the real H2 download regression fails before the fix and passes after it."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TEST = "h2_one_way_download_crosses_lease_boundary"
WAIT = """                    if self.pending_writable {
                        self.sink.wait_writable().await?;
                    }
                    self.pending_writable = false;
"""


def probe():
    return subprocess.run(
        ["cargo", "test", "--locked", "-p", "solartt-agent", "--test", "transport", TEST,
         "--", "--exact", "--nocapture"],
        cwd=ROOT, capture_output=True, text=True, timeout=1800,
    )


def main():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_OS") != "Linux"
            or not str(ROOT).startswith("/home/runner/work/")):
        raise SystemExit("Native regression builds require a disposable GitHub-hosted runner")
    source = ROOT / ".upstream/lib/src/pipe.rs"
    fixed = source.read_bytes()
    baseline = fixed.decode()
    replacements = [
        ("    pending_writable: bool,\n", ""),
        ("            pending_writable: false,\n", ""),
        (WAIT, "                    self.sink.wait_writable().await?;\n"),
        ("                    self.pending_writable = !unsent.is_empty();\n", ""),
    ]
    for before, after in replacements:
        if baseline.count(before) != 1:
            raise SystemExit("Backpressure fix shape changed; review the baseline reconstruction")
        baseline = baseline.replace(before, after, 1)
    private = ROOT / ".dev/backpressure-regression"
    private.mkdir(parents=True, exist_ok=True)
    try:
        source.write_text(baseline)
        red = probe()
        (private / "before.log").write_text(red.stdout + red.stderr)
        if red.returncode == 0 or "1 failed" not in red.stdout or "Elapsed" not in red.stdout + red.stderr:
            raise SystemExit("Regression did not reproduce the previous implementation's download stall")
        print("Previous implementation: expected download timeout reproduced", flush=True)
    finally:
        source.write_bytes(fixed)
    green = probe()
    (private / "after.log").write_text(green.stdout + green.stderr)
    if green.returncode or "1 passed" not in green.stdout:
        raise SystemExit("Fixed implementation failed the real H2 download regression")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    (output / "backpressure-regression.json").write_text(json.dumps({
        "status": "PASS", "test": TEST,
        "previous_implementation": "FAIL: expected download timeout",
        "fixed_implementation": "PASS: complete one-way download and exact accounting",
        "scope": "Real TLS/H2 forwarding on a disposable runner, limited and unlimited users",
    }, indent=2) + "\n")
    print("Fixed implementation: one-way download and accounting PASS", flush=True)


if __name__ == "__main__":
    main()
