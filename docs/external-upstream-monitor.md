# External control of missing upstream checks

Status: integration/checker prepared; external monitoring and notification
delivery are **not activated or verified** by this change. The selected route is
[Healthchecks with success signals](healthchecks-setup.md), which requires no
spare server. Keep weekly manual review until its activation checklist passes.
No timer is installed on Riga, the operator's Codex host or any other server.

The watcher can report an error only after it starts. A disabled workflow,
missing runner or dropped schedule needs another observer. A second workflow in
the same repository shares GitHub's scheduler/inactivity failure modes and is not
an independent timer. In the selected scheme, GitHub only sends a success signal;
Healthchecks independently detects its absence and sends notifications.

## Selected route: Healthchecks

Follow the [exact account, 7-day period + 3-day grace, secret and opt-in setup](healthchecks-setup.md).
Only successful fresh normal watcher attempts send empty HTTPS POSTs. Dry runs,
notification tests and stale retries cannot extend the external ten-day window.
The read-only checker below remains an optional audit/alternative for an existing
external monitoring host; deploying it is not required for Healthchecks.

## Optional read-only checker

Run on a separate monitoring service/host with Python 3.11+ and HTTPS access to
`api.github.com`. Copy the reviewed `scripts/check_trusttunnel_freshness.py` and
`scripts/github_api.py` together. It never writes issues, imports VPN profiles or
connects to a VPN server. Public data works without authentication; optional
`GH_TOKEN` needs only Actions read access and increases API allowance. Supply it
through the external executor's secret mechanism; never commit it or put it in
command arguments.

```sh
timeout 180s python3 -B /opt/solartt-monitor/check_trusttunnel_freshness.py
```

The process prints sanitized JSON with status and an evidence link:

| Exit | Meaning | Required external notification |
| --- | --- | --- |
| 0 | At least one successful normal check within 10 days | Healthy/recovery |
| 2 | No qualifying check, older than 10 days, or workflow not active | Alert |
| 3 | API/network/rate-limit/malformed-response/clock error | Unable to verify; alert |
| 124 / other nonzero | Executor timeout or unexpected failure | Unable to verify; alert |

Configure the external executor to run daily, alert on nonzero exit, and send a
recovery after the next healthy result. Deduplicate repeated failures there.
Use a channel independent of GitHub Issues (for example the operator's existing
monitor's email delivery). A process exit or a local journal entry alone is not
notification delivery. The executor also needs its own missed-run/dead-man check;
otherwise its failure merely moves the original blind spot.

The checker reads the repository's actual default branch and workflow state, then
reads paginated workflow runs and the exact attempt's paginated jobs. It accepts
only successful completed schedule/manual runs on that branch whose successful
`watch` job contains **Record successful normal TrustTunnel check**. That step
runs only after successful discovery with `dry_run=false` and no notification
test. Its API `completed_at` is the observation time. A green dry run or test
recovery cannot hide a stale monitor. Do not rename that step without updating
the checker and reviewing this contract.

Run ID, API order and workflow creation time do not define freshness. A full
rerun of an older run can provide a fresh observation; a reporter-only retry
cannot turn the old watch completion time into a fresh one. Exactly 10 days is
still healthy; **more** than 10 days alerts. Successful workflow completion is
required, so a failed reporter is not counted as a fully healthy normal run.
Earlier successful attempts remain eligible even if a later retry fails or is
still running; a retry does not erase the prior observation or refresh its time.
The OK result identifies a qualifying witness, not necessarily the newest run.

Before activation, old runs without this receipt step are not accepted. Run a new
normal watcher after merging. Without a recent witness, the checker exhausts the
history rather than assuming API order; a large history may require a read token.
API errors and the 180-second external timeout must alert as UNKNOWN, never OK.

## Activation and controlled acceptance

1. Select an executor and an independent delivery channel. Confirm ownership,
   access and any cost before provisioning. No server or paid service is created
   automatically from this repository.
2. Merge the receipt/checker change, run a new normal watcher from the default
   branch and run the checker read-only. Verify exit 0 and its matching attempt.
3. Connect the executor's daily schedule, nonzero/recovery notifications and its
   own missed-run alert. Confirm actual receipt with the owner.
4. Use the unit-test fixtures or the external monitor's test input to exercise
   stale/disabled, API error and recovery delivery. Do not disable the working
   watcher, change its pin or wait ten days to test notification routing. Do not
   label a synthetic routing test as an actual overdue watcher incident.
5. Record executor/channel identifiers privately, reviewed checker commit,
   observation/run links, daily schedule, alert/recovery delivery confirmation and
   the external executor's missed-run test. Only then replace the manual fallback.

API references: [workflow runs](https://docs.github.com/en/rest/actions/workflow-runs)
and [jobs for an exact attempt](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt).
