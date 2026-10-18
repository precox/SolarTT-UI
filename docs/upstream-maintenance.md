# Maintaining the TrustTunnel dependency

SolarTT-UI is an independent panel and managed agent over TrustTunnel. The agent
contains `upstream/0001-managed-policy.patch`; replacing it with an official
TrustTunnel binary loses managed policy behavior. Production builds use the
reviewed commit and archive SHA256 in `upstream/pin.json`, never a moving tag.

## Discovery and activation

`.github/workflows/watch-trusttunnel.yml` runs on Mondays at **07:23 UTC** and
supports **Actions → Watch TrustTunnel releases → Run workflow**. Select the
default branch. The optional `dry_run` input reports candidates without filing
issues or changing health issues. Normal scheduled and manual runs create one
issue for **each** stable version newer than the pinned version, in ascending
version order.

The workflow must first be reviewed and merged into the repository's default
branch (`main`). A PR or a successful unit test does not activate monitoring.
After merging, verify Actions and this workflow are enabled, run a manual dry
run, then a normal run, and inspect the logs. No PAT or server credentials are
needed: the job uses only `contents: read` and `issues: write` on the built-in
`GITHUB_TOKEN`. Organization policy must allow these permissions and Issues must
be enabled. Checkout does not persist credentials; there are no deployments,
environments, server secrets or self-hosted runners.

GitHub runs schedules only from the default branch and may delay or drop runs
during load. Public-repository schedules can be disabled after 60 days without
repository activity. Check the Actions page periodically, re-enable the workflow
if needed, and use manual dispatch after an interruption. See GitHub's
[schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
The job also skips forks and refs other than this repository's default branch.

## Selection, identity and failures

`scripts/watch_trusttunnel.py` uses only Python's standard library. It reads all
pages of the public releases API, excludes drafts and API-marked prereleases,
and accepts only `vX.Y.Z` or `X.Y.Z` tags with canonical numeric components.
Beta, RC, alpha, preview, build suffixes and unrecognized tags are excluded even
if the API incorrectly labels them stable. Version comparison is numeric;
neither API order, publication date nor the `/releases/latest` shortcut selects
the candidate. A republished older version does not become an upgrade.

The pin records the exact release `tag` as well as the commit and archive SHA256.
The watcher requires that tag to identify a published stable release and resolves
it through the commits API (including annotated tags) to verify the pinned commit.
A newer tag on the same commit is still a new version and gets its own review
task; matching source commits never advance the current version automatically.
`target_commitish` is not trusted: it can name a branch. Missing or invalid pins,
unpublished/non-stable pinned tags, tag/commit mismatches, ambiguous version
aliases, unresolvable tags and malformed API responses fail the run before any
issue is created. Proposed commits in issues are observations; the update PR must
verify the source and calculate the archive checksum independently. Dependency
preparation continues to download by immutable commit and verify the archive SHA256.

Deduplication reads all pages of **open and closed** issues, excluding PRs. Each
task has a canonical version in its title and a hidden marker containing the
upstream repository and version. Either identity suppresses another issue.
Preserve the marker when editing the title. Closing a task means that version
stays triaged; reopen the same issue to revisit it. Deleting the issue or removing
both identities permits recreation. Do not run independent issue-creating copies
of the script concurrently. Scheduled and manual workflow runs share one
concurrency group with cancellation disabled.

API requests have 30-second timeouts. Transient GET/server/network failures
receive at most three attempts with short backoff. Rate limits and responses
with `Retry-After` fail immediately for a later workflow rerun instead of retrying
before GitHub allows it. Persistent failures exit nonzero and surface as failed
Actions runs, never as “no releases”. Discovery and
deduplication finish before the first write. POST is never retried automatically:
if the response is lost, the next run reconciles the existing issue. A run can
create some issues before a later POST fails; rerun after investigating the
Actions error. Existing tasks are preserved. The workflow has a ten-minute cap;
large histories that exceed it require maintainer investigation.

## Failure notifications and recovery

After a normal scheduled or manual run, a separate `report-health` job handles
the watcher job's result, including failed tests and interrupted/timed-out checks:

- First failure: create `upstream: TrustTunnel release watcher needs attention`.
- Repeated failure: update the same issue with the latest failed attempt link.
- Successful normal run: close the issue with a recovery attempt link, retaining
  the last failure text. Success without an existing incident creates no issue.
- Later failure: reopen the same closed issue instead of creating a duplicate.

The reporter first limits managed issues to the GitHub.com `github-actions[bot]`
account (numeric user ID `41898282`, type `Bot`, as returned by the API). The
hidden `<!-- solartt-upstream-watch:health -->` marker and a title fallback then
identify the service issue across all pages of those open and closed issues.
Human-created issues, other bots, unknown authors and PRs are ignored even if
they copy the title or marker, including inside a code block. Such copies cannot
be overwritten/closed or block a real incident as duplicate matches. Preserve
the marker; keep investigation notes in comments because automation replaces the
issue body on failure. Multiple matching
bot-owned health issues cause an error requiring manual consolidation. Mutating
API calls are never blindly retried; a fresh normal run reconciles lost write
responses. The write response must also identify the expected bot-owned issue.

The watcher records its actual `GITHUB_RUN_ID` and `GITHUB_RUN_ATTEMPT` in a first
step before checkout/tests and passes those values as job outputs. Before reading
or changing issues, the reporter requires both to match its current run and
attempt. Missing or stale outputs fail the reporting job without API access.
This prevents an old reporter-only retry from closing a newer incident or
creating a false incident from a stale failure. A full rerun of an older run is
allowed when the watcher actually executes again in the new attempt; run ID
ordering alone does not establish freshness.

After a reporting error, use **Re-run all jobs** or start a new normal manual run.
**Re-run failed jobs** may rerun only the reporter when the watcher previously
succeeded, leaving stale outputs; that retry is deliberately rejected. Re-runs
use their original source revision, so after merging a reporter fix, start a new
run from the updated default branch instead of rerunning a pre-fix workflow.

The reporter runs on another GitHub-hosted runner with only `contents: read`
and `issues: write`. It does not import the discovery script or copy error output,
logs, environment values, profiles or credentials into GitHub. The shared API
client is `scripts/github_api.py`. Both jobs remain in the same serialized workflow
concurrency group. Dry runs and skipped watcher jobs do not change health issues;
a dry-run success cannot close an incident. A cancelled watcher job is reported
as incomplete if GitHub can still run the reporter. Cancelling the whole workflow
can prevent the reporting job from running, so cancellation alerts are best effort.
Health issue writes are supported only in the repository's Actions workflow with
its built-in `GITHUB_TOKEN`; local CLI use is read-only. A personal token creates
issues under a different author and is not a substitute for that workflow token.

To receive issue notifications, subscribe to **Watch → Custom → Issues** on the
repository and select GitHub/email delivery in your personal notification
settings. A created or reopened incident gives you a task to inspect; repeated
failures update its body without posting repeated comments. Check Actions and
personal Actions notification settings as well: unavailable Issues/API service,
token restrictions or a failed reporting job can prevent issue delivery.

### Controlled notification delivery test

Use **Actions → Watch TrustTunnel releases → Run workflow**, select the default
branch and leave `dry_run=false`. The manual `notification_test` choice defaults
to `none`; scheduled runs always use normal discovery. Test runs have `[TEST]`
in the run name, skip release discovery entirely and never change a pin, simulate
an upstream release, publish packages or contact servers. They use the same
reporting job, freshness/ownership checks, built-in token and concurrency group.

The separate issue is titled **[TEST] TrustTunnel watcher notification delivery**
and has marker `<!-- solartt-upstream-watch:notification-test -->`. Its body says
`TEST ONLY`. Test mode ignores real health issues; normal monitoring ignores test
issues, including when a title was edited to match the other mode. Preserve the
marker. Human-created copies are ignored, so do not create the test issue manually.

Run each step as a **new manual dispatch**, waiting for completion before the next:

1. Select `notification_test=failure`. The deliberately failed `watch` job is
   expected; `report-health` must succeed with `notification_test: true` and
   `action: create` (or `reopen` if a previous test issue exists). Verify its author
   is `github-actions[bot]`, the title/body clearly identify a test and the attempt
   link points to this run. Confirm the actual Issue notification in your chosen
   GitHub/email channel; an Actions-failure notification alone is not that proof.
2. Select `failure` again. Expect `action: update`, the same issue number and no
   duplicate. Body updates are not expected to produce a fresh Issue notification.
3. Select `recovery`. Both jobs must succeed; expect `action: close` on the same
   test issue, with a clearly marked test recovery link. Confirm the close event
   and its delivery according to your notification settings.
4. Select `failure` again. Expect `action: reopen` on the same issue. Check receipt
   of the reopened Issue notification.
5. Select `recovery` once more to leave the test issue closed. Keep it for reuse
   and record run/issue links and the owner's delivery confirmation. Do not
   publish private notification contents or addresses as evidence.

With `dry_run=true` the health reporter is skipped, so no notification is sent.
A `recovery` run without an existing test issue does nothing. A successful test
recovery does not establish a successful upstream discovery run. After testing,
run once with `notification_test=none`, `dry_run=false` to verify normal discovery
and health reporting still succeed. Never use historical pre-fix reruns for this
test; start from the updated default branch.

Actions/API results establish Issue writes and lifecycle only. Delivery remains
unverified until the owner confirms receipt; this workflow cannot read their
inbox. Record unobserved notifications as unverified rather than assuming success.

This does **not** detect a workflow that never starts, is disabled, cannot obtain
a runner or is cancelled before reporting. Until an independent check is configured, review the
Actions page weekly. Investigate if there has been no successful **normal** run
for ten days. A check for this must run independently of this scheduled workflow;
adding another step to it cannot detect its own missing start. GitHub's 60-day
inactivity shutdown applies to public repositories. Neither an external watchdog
nor a human acceptance test environment is installed by this change.

The selected [Healthchecks setup](healthchecks-setup.md) uses an external ten-day
countdown and fresh normal-run success signals, without another server. Its
repository secret, explicit opt-in variable and real delivery still need
activation/verification. The [read-only external checker](external-upstream-monitor.md)
remains an optional audit/alternative. Green dry runs and notification tests
refresh neither method.

Local read-only checks (no build or server access):

```sh
python3 -B -m unittest discover -s scripts -p 'test_*trusttunnel*.py'
python3 -B scripts/watch_trusttunnel.py
```

The second command reads the public API without authentication by default; an
optional `GH_TOKEN` increases the API allowance. It never writes unless explicitly
given `--create-issues`. Unit tests use synthetic API responses, including
pagination, numeric ordering, prerelease filtering, closed tasks, API failures and
the service issue create/update/close/reopen lifecycle, stale reporter-only retries,
fresh full reruns and untrusted issue copies without live GitHub writes.
They run in portable CI and before each discovery job.

## Updating a selected release

1. Triage the issue and create `upstream/trusttunnel-vX.Y.Z`. Review release notes,
   source changes, wire/client compatibility, configuration, managed hooks,
   HTTP/2 forwarding, quota accounting and revocation behavior.
2. Port the managed patch against the chosen source. Update `upstream/pin.json`
   with the exact release tag, commit and independently verified archive SHA256. Review
   `scripts/prepare_upstream.py` and `scripts/update_patch.py` when the source
   layout changes; retain SHA verification and modified-source notices. Run the
   preparation script to reconstruct the pinned patched dependency. Never drop
   managed behavior to make an upstream binary fit.
3. Review Rust dependencies/lockfiles, redistribution obligations, exact notices
   and license review records. Check client and fixture pins separately; an
   endpoint release does not automatically justify advancing them.
4. Pass the full [release gates](release-gates.md) on disposable GitHub-hosted
   runners. Preserve `scripts/check_managed_backpressure.py`: it must reproduce
   the old H2 download timeout before the fix and complete the download with
   exact accounting after it. If upstream changes the implementation, explicitly
   review and adapt its baseline reconstruction rather than disabling the test.
   Keep `h2_one_way_download_crosses_lease_boundary`, quota admission/exhaustion
   tests and `real_tls_revocation_closes_a_and_preserves_b_tcp_and_udp`.
5. Open a PR linked to the issue with compatibility findings, source/checksum
   evidence and CI results. Use
   [the upstream update template](../.github/PULL_REQUEST_TEMPLATE/upstream-update.md):
   select it with `template=upstream-update.md` in the PR form URL. Newly created
   discovery issues include a compare link that selects it after the review
   branch is pushed. The template records current/proposed identities, managed
   patch decisions, API/schema/config/client compatibility, the six CI gates,
   human acceptance and recovery limitations. Do not check unverified boxes.
   The pilot gate runs both historical alpha.1 migration and published alpha.5
   → candidate upgrade/recovery on separate disposable VMs. Record both exact
   reports; the historical alpha.1 pilot alone does not verify alpha.5. For agent
   or panel behavior changes, use the [prepared manual acceptance kit and procedure](manual-acceptance.md)
   and record the owner's decision. Kit creation is not human acceptance.
   Merge after review and create a
   **new SolarTT release** using [the releasing process](releasing.md). An upstream release
   alone does not establish compatibility or authorize publication.
6. Installation on Riga is a separate operational task in an agreed window:
   preserve the current package/provenance, make a backup with its matching key,
   and prepare and verify a recovery plan following
   [backup and upgrade](backup-upgrade.md). Installation requires separate
   authorization; discovery never connects to nodes or restarts VPN services.

Only discovery and issue creation are automated. Patch porting, pin changes,
merges, package publication and installation remain explicit reviewed actions.
