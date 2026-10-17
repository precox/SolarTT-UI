# Maintaining the TrustTunnel dependency

SolarTT-UI is an independent panel and managed agent over TrustTunnel. The agent
contains `upstream/0001-managed-policy.patch`; replacing it with an official
TrustTunnel binary loses managed policy behavior. Production builds use the
reviewed commit and archive SHA256 in `upstream/pin.json`, never a moving tag.

## Discovery and activation

`.github/workflows/watch-trusttunnel.yml` runs on Mondays at **07:23 UTC** and
supports **Actions → Watch TrustTunnel releases → Run workflow**. Select the
default branch. The optional `dry_run` input reports candidates without filing
issues. Normal scheduled and manual runs create one issue for **each** stable
version newer than the pinned version, in ascending version order.

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

The pin has no version field. To establish the current version, the watcher
resolves stable release tags through the commits API (including annotated tags)
and requires an exact match to the pinned commit. `target_commitish` is not
trusted: it can name a branch. Unknown pins, ambiguous version aliases,
unresolvable tags and malformed API responses fail the run before any issue is
created. Proposed commits in issues are observations; the update PR must verify
the source and calculate the archive checksum independently.

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

Local read-only checks (no build or server access):

```sh
python3 -B -m unittest discover -s scripts -p test_watch_trusttunnel.py
python3 -B scripts/watch_trusttunnel.py
```

The second command reads the public API without authentication by default; an
optional `GH_TOKEN` increases the API allowance. It never writes unless explicitly
given `--create-issues`. Unit tests use synthetic API responses, including
pagination, numeric ordering, prerelease filtering, closed tasks and API failures.
They run in portable CI and before each discovery job.

## Updating a selected release

1. Triage the issue and create `upstream/trusttunnel-vX.Y.Z`. Review release notes,
   source changes, wire/client compatibility, configuration, managed hooks,
   HTTP/2 forwarding, quota accounting and revocation behavior.
2. Port the managed patch against the chosen source. Update `upstream/pin.json`
   with the exact commit and independently verified archive SHA256. Review
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
   evidence and CI results. Merge after review and create a **new SolarTT
   release** using [the releasing process](releasing.md). An upstream release
   alone does not establish compatibility or authorize publication.
6. Installation on Riga is a separate operational task in an agreed window:
   preserve the current package/provenance, make a backup with its matching key,
   and prepare and verify a recovery plan following
   [backup and upgrade](backup-upgrade.md). Installation requires separate
   authorization; discovery never connects to nodes or restarts VPN services.

Only discovery and issue creation are automated. Patch porting, pin changes,
merges, package publication and installation remain explicit reviewed actions.
