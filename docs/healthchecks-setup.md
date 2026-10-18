# Healthchecks setup for missing watcher runs

Status: integration prepared, **not activated or delivery-tested**. The owner
selected this approach; a separate checker host is not needed. Keep manual
weekly review until the live activation and notification tests below pass.
The persistent human-acceptance environment remains deferred because no spare
host is available; its passive kit and both CI upgrade pilots remain usable.

## Account and check

Create/sign in to a Healthchecks.io account with your notification email. No
GitHub OAuth repository access, GitHub PAT, server access or management API key
is required. The free Hobbyist plan currently covers 20 checks; this uses one.

Create a check with the following settings:

| Field | Value |
| --- | --- |
| Name | SolarTT-UI — TrustTunnel watcher |
| Schedule type | **Simple** |
| Period | **7 days** (604800 seconds) |
| Grace Time | **3 days** (259200 seconds) |
| Allowed HTTP Request Methods | **Only POST** |
| HTTP request body/content filtering | Off |
| Email integration | Enabled for this check; destination confirmed |

Period plus grace means an alert **10 days after the last accepted success
signal**. Simple mode measures an interval and does not need a cron timezone.
The normal watcher remains weekly on Monday at 07:23 UTC. A successful normal
manual run also renews the interval. A new check starts as New; absence monitoring
must not be assumed active before the first confirmed ping.

Use the UUID success URL in the exact format `https://hc-ping.com/<check-uuid>`.
It must not contain `/start`, `/fail`, a query string or a project API key. Do not
open it in a browser or put it in a chat/screenshot/issue. POST-only filtering
also prevents ordinary link previews from sending a success signal. Treat the
URL as a credential: disclosure permits forged signals, but grants no repository
or server access. If exposed, replace the check/URL and update the secret.

The signal has an empty body. We send no logs, profiles, environment dump,
credentials or repository token. The service receives request timing and the
GitHub runner's outbound address; account/email information stays with the
provider under its privacy policy. HTTPS is verified, redirects are refused,
requests have a 15-second deadline, and URL-bearing errors are redacted. The
script requires the documented HTTP 200 **and** `OK` body; an unknown/rate-limited
check is not accepted as confirmed delivery.

## GitHub repository settings

In `precox/SolarTT-UI` → **Settings → Secrets and variables → Actions**:

1. **Secrets → New repository secret**:
   - Name: `HEALTHCHECKS_TRUSTTUNNEL_PING_URL`
   - Value: the full private HTTPS UUID success URL.
2. After reviewed code is merged and the secret exists, **Variables → New
   repository variable**:
   - Name: `TRUSTTUNNEL_HEARTBEAT_ENABLED`
   - Value: `true` (lowercase).

The variable is an explicit opt-in. Missing/false skips heartbeat delivery while
the existing watcher and health issue lifecycle continue. With it enabled, a
missing/invalid secret or failed delivery makes the heartbeat job fail visibly;
it never prints the URL. Turning it off later does not pause Healthchecks: the
external countdown continues and will alert without signals.

The job needs only `contents: read` for pinned checkout, does not persist its
credentials and receives no GitHub API token in its script environment. It runs
after successful watch/report-health jobs only on this repository's default
branch. It shares their serialized workflow concurrency group. Notification
tests and dry runs do not signal Healthchecks.

It also checks actual watcher run/attempt provenance and the normal-check
completion timestamp. A heartbeat-only retry is rejected; a delayed observation
older than 30 minutes is rejected. Use a **new normal dispatch** to recover.
The ten-day external interval begins at accepted delivery, normally seconds
after discovery; the freshness bound prevents an arbitrarily delayed job from
renewing it using an old observation. Small runner clock skew up to 30 seconds
is tolerated; larger future timestamps fail closed.

## Live activation sequence

1. Create the check/settings above. Enable its email integration and use the
   integration's test notification; confirm actual receipt. This proves email
   routing only, not missing-run detection.
2. Store the repository secret. Review and merge the prepared PR; do not assume
   a PR CI run can activate this default-branch-only integration.
3. Enable the repository variable. Start a **new** manual `Watch TrustTunnel
   releases` run from `main`, `dry_run=false`, `notification_test=none`.
4. Verify watch, report-health and heartbeat all pass. The heartbeat log must
   confirm delivery without showing its URL. Healthchecks must show Up and a
   recent POST success event matching this run's time. A green Actions run alone
   is not proof if heartbeat was skipped.
5. Check missing-ping and recovery delivery with a **separate clearly marked TEST
   check**, not by stopping the real watcher or shortening its production limit.
   For the test check use a one-minute period and one-minute grace, POST-only,
   the same email integration, and a controlled empty POST from the owner's
   trusted client. Confirm its Down email after expiry, then another POST and
   the recovery email. Keep its URL separate from the repository's real secret.
   If this step is not performed, record expiry/recovery delivery as unverified.
6. Retain sanitized run links and receipt confirmation; never retain the ping
   URL or private email contents in the repository. Recheck the real check still
   has 7-day period, 3-day grace, email enabled and the correct GitHub secret.
   Delete/archive the TEST check after its evidence is recorded.

The normal issue-based error reporter remains useful for failures of runs that
start. Healthchecks independently waits for success signals, so disabled Actions,
dropped schedules, unavailable runners or an unreachable GitHub service cannot
send a false success. A Healthchecks outage or mail delivery failure can still
delay the external alert; do not describe this as an absolute delivery guarantee.

Provider references: [check settings](https://healthchecks.io/docs/configuring_checks/),
[notifications](https://healthchecks.io/docs/configuring_notifications/),
[ping API](https://healthchecks.io/docs/http_api/),
[pricing](https://healthchecks.io/pricing/) and
[privacy](https://healthchecks.io/privacy/).
