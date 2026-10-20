# Self-hosted Watcher control with Telegram

Status: implementation and installation procedure prepared; **not deployed**.
No target host, production VPN or existing Telegram bot is changed by this PR.
The selected destination is the owner's existing VPN events chat. Keep the bot
identity, host address, chat ID and credentials outside the public repository.

## Operation and boundaries

Use a separate Ubuntu host with Python 3.11+ and systemd (Ubuntu 24.04 recommended).
The small oneshot service runs hourly, with up to three minutes of timer slack,
and reads public GitHub Actions data using the existing
[freshness checker](external-upstream-monitor.md). It accepts only successful
normal watcher observations, not dry runs or notification tests. More than ten
days without a qualifying observation or a disabled workflow is CRITICAL;
API/rate-limit/network errors, a checker crash or its 180-second timeout are UNKNOWN.
Detection is within the next hourly check plus timer slack and check runtime;
it is not an exact alarm at the ten-day instant.

The Telegram sender posts an incident, a changed incident type, a daily reminder
while unhealthy and one recovery. Initial healthy observations are quiet.
State is locked and atomically persisted in a private service directory. A failed
Telegram response does not acknowledge the transition: the next hourly check
tries again if that state still applies. An ambiguous lost response or a crash
after delivery but before state persistence can produce a duplicate. There is
no claim of exactly-once delivery. A brief incident that ends while Telegram is
unavailable may never be delivered; there is no historical-event queue.

Send only status and allowlisted public Actions evidence. Never send profiles,
keys, databases, HTTP error bodies or diagnostic logs. Telegram acceptance is
checked, but only the owner can confirm actual receipt/readability in the chat.
This service does not forward all VPN events or new-release Issues to Telegram.
The separate [dependency event observer](dependency-maintenance.md#telegram-delivery-on-the-existing-monitor-host)
can deliver audit/PR/CI events after its own deployment and acceptance. Existing
VPN event delivery continues through its current sender.

The existing bot can be used for outgoing `sendMessage` requests. This service
does not call `getUpdates`, register a webhook or replace the bot's running
process. The bot must already be allowed to send to the selected chat. If it is
a group with topics, configure the existing destination topic as described below.

Only outbound HTTPS to GitHub and Telegram is required. No listening socket,
public DNS name, incoming firewall rule, VPN credential or server restart is
needed. The systemd service has a dynamic unprivileged user, read-only system
paths, private state, no capabilities, 128 MiB memory limit, 10% CPU quota and
eight-task limit. These are limits, not measured baseline consumption. It never
installs a SolarTT package, reads another project's data or controls VPN services.

**Failure of this monitoring host or its timer remains a blind spot.** Its own
independent missed-run observer is not implemented here. At least weekly, check
the timer, `state.json`'s `last_checked_at` and delivery health from another
machine. Local journal output alone is not independent notification delivery.
A corrupt state file or an invalid credential causes a visible service failure,
not an automatic reset or a claim of healthy monitoring.

## Install only after host review

These commands are a reviewable manual procedure, not an automatic deployment.
First establish authorized SSH access and verify the host key through an existing
trusted channel. Check Ubuntu/Python versions and available resources; identify
the existing bot service and where its credentials and numeric chat ID live
without printing them. Do not guess SSH credentials, rotate the bot token,
restart that bot, alter VPN packages or change firewall/routing settings.

From a checkout of the exact reviewed commit on the monitoring host, verify:

```sh
python3 --version
systemd --version
git rev-parse HEAD
```

For a **first install** (inspect and preserve any existing monitor installation
before updating), copy only the three reviewed Python files and two units:

```sh
sudo install -d -m 0755 /opt/solartt-upstream-monitor
sudo install -m 0644 scripts/github_api.py scripts/check_trusttunnel_freshness.py scripts/notify_trusttunnel_telegram.py /opt/solartt-upstream-monitor/
sudo install -m 0644 packaging/monitor/solartt-upstream-monitor.service packaging/monitor/solartt-upstream-monitor.timer /etc/systemd/system/
sudo install -d -m 0700 /etc/solartt-upstream-monitor
sudo install -m 0600 /dev/null /etc/solartt-upstream-monitor/telegram_token
sudo install -m 0600 /dev/null /etc/solartt-upstream-monitor/telegram_chat_id
sudo install -m 0600 /dev/null /etc/solartt-upstream-monitor/github_token
```

Populate `telegram_token` and `telegram_chat_id` locally with a trusted editor
or secret-management tool. Use the existing bot and destination; do not paste
credentials into shell command arguments, chat, terminal output or this repo.
Keep `github_token` empty initially: public data needs no authentication.
If the public API limit is insufficient, populate it with a token restricted
to this repository and Actions read access; never provide Issues/write access.
The root-owned credential sources remain 0600; `LoadCredential` provides private
readable copies to the service. Do not change the other bot's credential files.

For an existing Telegram topic only, use `sudo systemctl edit
solartt-upstream-monitor.service` with this non-secret setting:

```ini
[Service]
Environment=TELEGRAM_MESSAGE_THREAD_ID=REPLACE_WITH_EXISTING_NUMERIC_TOPIC_ID
```

Omit the setting for the chat without a topic. Use the same numeric topic in the
test command if applicable, with an additional systemd-run property
`-p Environment=TELEGRAM_MESSAGE_THREAD_ID=...`.

## Controlled delivery and activation

1. Validate the copied units without starting anything:

   ```sh
   sudo systemd-analyze verify /etc/systemd/system/solartt-upstream-monitor.service /etc/systemd/system/solartt-upstream-monitor.timer
   sudo systemctl daemon-reload
   ```

2. Send three explicitly marked TEST messages: stale, unable-to-verify and
   recovery. The test does not read GitHub, change pins, create Issues, touch VPN
   or write the live monitor state. Wait for this test to finish before repeating:

   ```sh
   sudo systemd-run --unit=solartt-upstream-monitor-delivery-test --wait --collect \
     -p DynamicUser=yes -p PrivateTmp=yes -p NoNewPrivileges=yes \
     -p LoadCredential=telegram_token:/etc/solartt-upstream-monitor/telegram_token \
     -p LoadCredential=telegram_chat_id:/etc/solartt-upstream-monitor/telegram_chat_id \
     -p LoadCredential=github_token:/etc/solartt-upstream-monitor/github_token \
     /usr/bin/python3 -B /opt/solartt-upstream-monitor/notify_trusttunnel_telegram.py --test-cycle
   ```

   Confirm all three messages arrived in the intended chat/topic from the right
   bot. Telegram's accepted response alone does not establish delivery to you.

3. Merge the watcher receipt change and start a **new** normal watcher on the
   default branch, with `notification_test=none` and `dry_run=false`. Old green
   workflows without the receipt step cannot establish a qualifying observation.
   Keep `TRUSTTUNNEL_HEARTBEAT_ENABLED` unset/false: the selected self-hosted
   route does not use Healthchecks or its secret.

4. Run the actual service once:

   ```sh
   sudo systemctl start solartt-upstream-monitor.service
   sudo systemctl status solartt-upstream-monitor.service --no-pager
   sudo journalctl -u solartt-upstream-monitor.service -n 15 --no-pager
   ```

   Require `status: OK`. A successful oneshot normally becomes inactive after
   completion. CRITICAL/UNKNOWN intentionally exit nonzero even after delivery.
   Initial OK sends no message. Confirm the root-only state file has a recent
   `last_checked_at`; never publish state/credential files as diagnostics.

5. Enable the timer only after normal checking and TEST delivery pass:

   ```sh
   sudo systemctl enable --now solartt-upstream-monitor.timer
   sudo systemctl list-timers solartt-upstream-monitor.timer --no-pager
   ```

   Verify another real hourly execution and the state timestamp. Record the
   reviewed commit, normal Actions run URL, private host/channel identifiers,
   test receipt and next execution time privately. Only then treat this path as
   active. A PR, unit test or enabled timer alone does not prove monitoring works.

## Stop or remove this monitor

Stop only `solartt-upstream-monitor.timer` and any active
`solartt-upstream-monitor.service`; leave the existing VPN and bot running.
Remove only the two named units, `/opt/solartt-upstream-monitor` and its private
configuration/state after preserving evidence if needed, then daemon-reload.
Retain weekly manual Actions review whenever this monitor is stopped.

References: [Telegram sendMessage](https://core.telegram.org/bots/api#sendmessage),
[systemd credentials and sandboxing](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html),
[systemd timer semantics](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html).
