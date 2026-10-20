#!/usr/bin/env python3
"""Independent, read-only Actions check with durable Telegram notifications."""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CHECKER = Path(__file__).with_name("check_trusttunnel_freshness.py")
WORKFLOW_URL = "https://github.com/precox/SolarTT-UI/actions/workflows/watch-trusttunnel.yml"
REMINDER_SECONDS = 86400


class MonitorError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MonitorError("Telegram redirect refused")


def credentials():
    directory = Path(os.environ.get("CREDENTIALS_DIRECTORY", "/run/credentials/solartt-upstream-monitor.service"))
    try:
        token = (directory / "telegram_token").read_text().strip()
        chat = (directory / "telegram_chat_id").read_text().strip()
        github = (directory / "github_token").read_text().strip()
    except (OSError, UnicodeError):
        raise MonitorError("Cannot read monitor credentials") from None
    if not re.fullmatch(r"[1-9][0-9]{4,19}:[A-Za-z0-9_-]{20,100}", token):
        raise MonitorError("Invalid Telegram token format")
    if not re.fullmatch(r"-?[1-9][0-9]{0,19}", chat):
        raise MonitorError("Invalid numeric Telegram chat ID")
    topic = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID", "")
    if topic and not re.fullmatch(r"[1-9][0-9]{0,19}", topic):
        raise MonitorError("Invalid Telegram topic ID")
    return token, chat, github, int(topic) if topic else None


def send_message(token, chat, text, topic=None):
    payload = {"chat_id": chat, "text": text,
               "link_preview_options": {"is_disabled": True}}
    if topic is not None:
        payload["message_thread_id"] = topic
    try:
        request = urllib.request.Request(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        # No automatic POST retry: a lost response may already have delivered.
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            body = response.read(65537)
            if response.status != 200 or len(body) > 65536:
                raise ValueError()
            result = json.loads(body)
            message = result.get("result") if isinstance(result, dict) else None
            if (result.get("ok") is not True or not isinstance(message, dict)
                    or type(message.get("message_id")) is not int
                    or message["message_id"] <= 0
                    or not isinstance(message.get("chat"), dict)
                    or message["chat"].get("id") != int(chat)):
                raise ValueError()
    except Exception:
        # HTTP errors contain the credential-bearing URL; never print them or
        # the response body. Retry an unacknowledged transition next timer tick.
        raise MonitorError("Telegram delivery unconfirmed; will retry next check") from None


def run_check(github_token):
    env = dict(os.environ)
    env.pop("GH_TOKEN", None)
    if github_token:
        env["GH_TOKEN"] = github_token
    try:
        child = subprocess.run([sys.executable, "-B", str(CHECKER)], env=env,
                               capture_output=True, timeout=180, check=False)
        result = json.loads(child.stdout)
        expected = {0: "OK", 2: "CRITICAL", 3: "UNKNOWN"}.get(child.returncode)
        if expected is None or not isinstance(result, dict) or result.get("status") != expected:
            raise ValueError()
        return result
    except subprocess.TimeoutExpired:
        return {"status": "UNKNOWN", "reason": "checker_timeout"}
    except (OSError, ValueError, UnicodeError):
        return {"status": "UNKNOWN", "reason": "checker_failed"}


def identity(result):
    status = result["status"]
    # Never relay exception strings, API responses, logs or arbitrary URLs.
    reasons = {"workflow_not_active", "no_successful_normal_check_within_10_days",
               "recent_successful_normal_check", "checker_timeout", "checker_failed"}
    reason = result.get("reason")
    return {"status": status, "reason": reason if isinstance(reason, str) and reason in reasons
            else "verification_failed"}


def message(result, prefix=""):
    state = identity(result)
    if state["status"] == "OK":
        title = "🟢 TrustTunnel Watcher: проверки восстановились."
    elif state["status"] == "CRITICAL":
        title = ("🔴 TrustTunnel Watcher: workflow отключён."
                 if state["reason"] == "workflow_not_active" else
                 "🔴 TrustTunnel Watcher: нет успешной обычной проверки более 10 дней.")
    else:
        title = "🟠 TrustTunnel Watcher: не удалось проверить GitHub Actions."
    lines = [prefix + title]
    witness = result if result["status"] == "OK" else result.get("last_observed")
    if isinstance(witness, dict):
        observed = witness.get("observed_at", "")
        url = witness.get("run_url", "")
        if isinstance(observed, str) and re.fullmatch(r"[0-9T:+.Z-]{19,40}", observed):
            lines.append("Подтверждённая проверка: " + observed)
        if isinstance(url, str) and re.fullmatch(
                r"https://github\.com/precox/SolarTT-UI/actions/runs/[1-9][0-9]*/attempts/[1-9][0-9]*", url):
            lines.append(url)
    elif result["status"] == "CRITICAL":
        lines.append("Свежая успешная проверка не подтверждена.")
    lines.extend([WORKFLOW_URL, "Это контроль Watcher, не состояния VPN."])
    return "\n".join(lines)


def load_state(path, now):
    if not path.exists():
        return {"version": 1, "acknowledged": None, "notified_at": 0}
    try:
        state = json.loads(path.read_text())
        acknowledged = state["acknowledged"]
        if (state["version"] != 1 or type(state["notified_at"]) is not int
                or not 0 <= state["notified_at"] <= now + 300
                or (acknowledged is not None and (
                    not isinstance(acknowledged, dict)
                    or acknowledged.get("status") not in ("OK", "CRITICAL", "UNKNOWN")
                    or not isinstance(acknowledged.get("reason"), str)))):
            raise ValueError()
        return state
    except (OSError, ValueError, TypeError, KeyError):
        raise MonitorError("Monitor state unreadable; inspect locally, do not reset silently") from None


def save_state(path, state):
    # State directory is private and owned by the service, with one locked writer.
    fd, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def report(path, result, deliver, now=None, prefix=""):
    now = int(time.time()) if now is None else now
    state = load_state(path, now)
    current = identity(result)
    previous = state["acknowledged"]
    changed = current != previous
    unhealthy = current["status"] != "OK"
    needs_message = ((unhealthy and (changed or now - state["notified_at"] >= REMINDER_SECONDS))
                     or (not unhealthy and previous is not None and previous["status"] != "OK"))
    if needs_message:
        deliver(message(result, prefix))
        state["notified_at"] = now
    state.update(acknowledged=current, last_checked_at=now)
    save_state(path, state)
    return needs_message


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-cycle", action="store_true",
                        help="Send three clearly marked TEST messages using temporary state; no GitHub access")
    args = parser.parse_args()
    token, chat, github, topic = credentials()
    deliver = lambda text: send_message(token, chat, text, topic)
    if args.test_cycle:
        with tempfile.TemporaryDirectory(prefix="solartt-notification-test-") as folder:
            path = Path(folder) / "state.json"
            for status, reason in [("CRITICAL", "no_successful_normal_check_within_10_days"),
                                   ("UNKNOWN", "checker_timeout"),
                                   ("OK", "recent_successful_normal_check")]:
                report(path, {"status": status, "reason": reason}, deliver, prefix="[TEST] ")
        print("TEST delivery cycle accepted by Telegram; owner must confirm receipt")
        return
    directory = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/solartt-upstream-monitor"))
    with (directory / "monitor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MonitorError("Monitor already running") from None
        result = run_check(github)
        sent = report(directory / "state.json", result, deliver)
        print(json.dumps({"status": result["status"], "notification_sent": sent}))
        # A delivered incident is still an unhealthy service result in systemd.
        raise SystemExit({"OK": 0, "CRITICAL": 2, "UNKNOWN": 3}[result["status"]])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Includes unexpected failures and filesystem errors without leaking
        # credentials, raw checker output or API exception tracebacks to journal.
        raise SystemExit("Monitor failed; inspect configuration/state and delivery locally") from None
