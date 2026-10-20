#!/usr/bin/env python3
"""Separate Telegram observer: public metadata only, isolated from Watcher health."""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from github_api import DOWNSTREAM
from notify_trusttunnel_telegram import MonitorError, credentials, save_state, send_message

WORKFLOW_URL = f"https://github.com/{DOWNSTREAM}/actions/workflows/dependency-maintenance.yml"
FAILURE = {"audit": {"status": "UNKNOWN", "reason": "observer_failed", "url": WORKFLOW_URL}, "prs": []}


def snapshot(github, tracked, cursor=0):
    env = dict(os.environ)
    env.pop("GH_TOKEN", None)
    if github:
        env["GH_TOKEN"] = github
    try:
        child = subprocess.run([sys.executable, "-B", str(Path(__file__).with_name("scan_dependency_events.py"))],
                               input=json.dumps({"tracked": tracked, "cursor": cursor}).encode(), env=env,
                               capture_output=True, timeout=100)
        if child.returncode:
            return FAILURE
        return json.loads(child.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return FAILURE


def validate_snapshot(data):
    audit, prs = data["audit"], data["prs"]
    if (type(data.get("cursor", 0)) is not int or data.get("cursor", 0) < 0
            or type(data.get("deferred", False)) is not bool):
        raise MonitorError("Invalid observer progress")
    if audit.get("status") not in ("OK", "CRITICAL", "UNKNOWN") or not isinstance(prs, list) or len(prs) > 100:
        raise MonitorError("Invalid observer response")
    url = audit.get("url", "")
    if url != WORKFLOW_URL and not re.fullmatch(
            rf"https://github\.com/{DOWNSTREAM}/actions/runs/[1-9][0-9]*/attempts/[1-9][0-9]*", url):
        raise MonitorError("Invalid audit evidence URL")
    for pr in prs:
        number = pr["number"]
        if (type(number) is not int or number < 1 or not re.fullmatch(r"[0-9a-f]{40}", pr["head"])
                or pr["state"] not in ("open", "closed") or type(pr["draft"]) is not bool
                or pr["ci"] not in ("pending", "success", "failure")
                or (pr["ci"] != "pending" and not pr["ci_url"])
                or pr["url"] != f"https://github.com/{DOWNSTREAM}/pull/{number}"
                or (pr["ci_url"] and not re.fullmatch(
                    rf"https://github\.com/{DOWNSTREAM}/actions/runs/[1-9][0-9]*", pr["ci_url"]))):
            raise MonitorError("Invalid PR observation")


def load(path, now):
    if not path.exists():
        return {"version": 1, "audit": None, "prs": {}}
    try:
        state = json.loads(path.read_text())
        if (state["version"] != 1 or not isinstance(state["prs"], dict) or len(state["prs"]) > 1000
                or type(state.get("cursor", 0)) is not int or state.get("cursor", 0) < 0):
            raise ValueError()
        for entry in ([state["audit"]] if state["audit"] else []) + list(state["prs"].values()):
            if not isinstance(entry, dict) or type(entry.get("notified_at")) is not int or not 0 <= entry["notified_at"] <= now + 300:
                raise ValueError()
        return state
    except (OSError, ValueError, KeyError, TypeError):
        raise MonitorError("Unreadable dependency observer state; do not reset silently") from None


def report(path, data, deliver, now=None):
    validate_snapshot(data)
    now = int(time.time()) if now is None else now
    state = load(path, now)
    sent = 0

    def send(text):
        nonlocal sent
        if sent >= 3:
            return False
        deliver(text)
        sent += 1
        return True

    audit, old = data["audit"], state["audit"]
    bad = audit["status"] != "OK"
    if ((bad and (not old or old["status"] != audit["status"] or now - old["notified_at"] >= 86400))
            or (not bad and old and old["status"] != "OK")):
        title = ("🟢 SolarTT: ежедневная проверка зависимостей восстановилась." if not bad else
                 "🔴 SolarTT: ежедневная проверка зависимостей требует внимания." if audit["status"] == "CRITICAL" else
                 "🟠 SolarTT: не удалось проверить события обновлений.")
        if send(title + "\n" + audit["url"]):
            state["audit"] = {"status": audit["status"], "notified_at": now}
    elif old is None:
        state["audit"] = {"status": audit["status"], "notified_at": now}
    save_state(path, state)
    for pr in data["prs"]:
        number = str(pr["number"])
        old = state["prs"].get(number)
        if old is None or any(old.get(k) != pr[k] for k in ("head", "state", "draft")):
            if old is None and pr["state"] == "closed":
                continue
            title = f"🔔 SolarTT: PR #{number} " + ("закрыт." if pr["state"] == "closed" else "подготовлен или обновлён.")
            if pr["state"] == "open":
                title += "\n" + ("Нужна ручная доработка исправления." if pr["draft"] else "Обновление зависимостей ждёт ревью.")
            if not send(title + "\n" + pr["url"] + "\nВыпуск и установка — отдельно."):
                break
            previous_ci = old.get("ci") if old and old["head"] == pr["head"] else None
            state["prs"][number] = {**{k: pr[k] for k in ("head", "state", "draft")},
                                     "ci": previous_ci, "notified_at": now}
            save_state(path, state)
        old = state["prs"][number]
        if pr["state"] == "open" and pr["ci"] != "pending" and old.get("ci") != pr["ci"]:
            title = f"{'🟢' if pr['ci'] == 'success' else '🔴'} SolarTT: CI для PR #{number} "
            title += "прошёл. Требуется ревью." if pr["ci"] == "success" else "не прошёл. Требуется проверка."
            if not send(title + "\n" + pr["ci_url"]):
                break
            old.update(ci=pr["ci"], notified_at=now)
            save_state(path, state)
    state["prs"] = {k: v for k, v in state["prs"].items()
                    if v["state"] == "open" or now - v["notified_at"] < 30 * 86400}
    state["last_checked_at"] = now
    if "cursor" in data:
        state["cursor"] = data["cursor"]
    save_state(path, state)
    return sent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-cycle", action="store_true")
    args = parser.parse_args()
    token, chat, github, topic = credentials()
    def deliver(text):
        send_message(token, chat, text, topic)
        time.sleep(1.2)
    if args.test_cycle:
        for label in ("ошибка ежедневной проверки", "новый PR", "CI прошёл"):
            deliver("[TEST] SolarTT dependency notifications: " + label + ".\nТолько проверка доставки; реальный PR не создаётся.")
        print("TEST events accepted by Telegram; owner must confirm receipt")
        return
    folder = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/solartt-dependency-events"))
    with (folder / "events.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        now = int(time.time())
        state = load(folder / "events.json", now)
        tracked = [int(n) for n, entry in state["prs"].items() if entry["state"] == "open"]
        data = snapshot(github, tracked, state.get("cursor", 0))
        count = report(folder / "events.json", data, deliver, now)
        print(json.dumps({"audit": data["audit"]["status"], "notifications_sent": count,
                          "prs_deferred": data.get("deferred", False)}))
        raise SystemExit(0 if data["audit"]["status"] == "OK" else 3)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Dependency event observer failed; inspect configuration/state locally") from None
