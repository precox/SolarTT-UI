# Automatic dependency maintenance

Status: implementation prepared; scheduled execution, automatic PR creation and
the new Telegram observer require the activation checks below. CI preparation
or TEST delivery alone is not proof that the live mechanism is active.

## What runs automatically

`dependency-maintenance.yml` audits the production Cargo.lock against a freshly
fetched RustSec database every day at **06:41 UTC** and after relevant changes on
main. Manual dispatch defaults to `dry_run=true`. Audit errors fail the workflow;
they are never reported as zero vulnerabilities. The pinned audit binary and
its checksum are shared with the existing security gate. No advisory ignore list
or guard is relaxed. Existing unmaintained-dependency warnings remain visible in
the full security gate; they are not automatically resolved or suppressed.

With `DEPENDENCY_MAINTENANCE_ENABLED=true`, a separate job creates a proposal PR:

- One vulnerable crates.io package identity; one or more matching advisories.
- The minimum non-yanked **stable patch** in the same major/minor line satisfying
  every supported patched range. Prereleases are excluded independently of order.
- Registry dependencies, features and minimum Rust version are identical.
- The downloaded archive matches the official registry checksum; its declared
  license and every preserved notice match the existing exact review byte for
  byte. Supplemental/explicit license-file cases require manual review.
- Real Cargo resolution changes exactly this package version/checksum, preserves
  the remaining graph, and passes locked metadata resolution. A second audit of
  the same RustSec database snapshot must contain zero vulnerabilities.

Only Cargo.lock, this package's version in `upstream/license-review.json` (plus
the review date), and a structured public report under `docs/dependency-updates/`
can enter a patch PR. Refreshing an identity with identical license text is not
approval of new license terms. Full CI independently collects and verifies all
notices again before packaging.

Multiple vulnerable package identities, unsupported ranges, no compatible patch,
changed dependency requirements, changed notices, or failed Cargo preparation
produce a **draft PR containing only the report**. It explicitly requires manual
work and may have a red security gate until that work is done. Unexpected API,
checksum or audit failures stop processing; no plausible-looking fix is invented.

The minimum three-component comparator ranges (`>=`, `>`, `<=`, `<`, `=` with
comma conjunctions, including prerelease bounds) are supported conservatively.
Caret, wildcard and other expressions require manual review. Feature/minor/major
Rust upgrades are not attempted. Automatic preparation does not cover arbitrary
upstream source ports or every possible dependency update.

GitHub Actions updates use `.github/dependabot.yml`: weekly Wednesday 07:15 UTC,
at most two open PRs, with minor/patch grouping. Full SHA pinning is retained.
The custom Rust updater handles the generated `.upstream/lib` path and the exact
notice policy, which a generic dependency PR alone cannot satisfy.

TrustTunnel stable-release discovery remains the separate weekly watcher and
its maintenance Issues. Its pin/managed patch, historical baselines and lease,
quota and revocation regressions are not changed by this updater.

## GitHub permissions, retries and CI

The prepare job has only `contents: read`, runs on a disposable hosted runner,
and publishes only the bounded public proposal artifact. It has no Telegram,
server, release or deployment secrets. Cargo commands run only there. The writer
checks out the trusted default-branch revision and revalidates the artifact before
any write. It does not check out or execute the proposed branch's code. There is
no `pull_request_target` execution of untrusted code.

The writer has `contents: write`, `pull-requests: write` and `actions: write`.
It creates only `automation/security-<identity>` branches and PRs; it never force
pushes, updates main, merges, tags, publishes a package or contacts a server.
The proposal identity deduplicates both open and closed bot-owned PRs. Closing
an unresolved draft stays triaged; it does not make the audit healthy. Human PRs
and forks cannot impersonate this identity. At most three open security PRs are
allowed before a maintainer must review the queue.

Writes are not blindly retried. A new run reconciles a created branch or a lost
PR response. An orphan branch must match the exact approved one-commit data
delta; otherwise publication stops for investigation. Existing PRs and human
edits are preserved. If main moved during preparation, a new audit is required.

PRs written with GITHUB_TOKEN can create approval-required PR workflows. The
writer explicitly dispatches `ci.yml` on the verified proposal branch using
the built-in token; no PAT or additional GitHub App is needed. A prior dispatch
for the exact head suppresses another. The release job still requires an actual
alpha tag push, so this dispatch cannot publish. If a human changes the branch,
the writer will not dispatch unapproved code: request CI manually after review.
There is no automatic merge, even after green CI.

The daily workflow remains red while its audited default-branch lockfile has
vulnerabilities, even when it has created a PR. Only a new normal audit after the
fix is merged can establish recovery. Start a **new** dispatch on main after a
fix, not an old-source rerun. Dry runs do not carry the live receipt step used by
the Telegram observer.

## Telegram delivery on the existing monitor host

`scan_dependency_events.py` reads only public GitHub metadata. A separate
`solartt-dependency-events.service`/timer runs at minutes **07, 22, 37, 52 UTC**
(up to two minutes of timer slack). It shares the existing root-only credential
sources and Telegram destination, with its own DynamicUser, private state, lock,
128 MiB/10% CPU limits and 180-second timeout. It neither reads bot messages nor
changes the existing bot or Watcher freshness service. No inbound port is needed.

Messages cover daily-audit failure/recovery, a new or changed managed PR, its
head-specific CI result, and closing/reopening. Only our bot-owned security PRs
and same-repository Dependabot GitHub Actions PRs qualify. Titles, bodies, error
output, profiles and logs are never forwarded. A green CI for another head or
an approval-required run is not a passing result. PR closure is not a deployment.

The audit signal requires a new normal workflow invocation created within three
days, on the actual default branch. Missing/disabled audits or failures alert;
dry runs cannot close an incident. Old reruns beyond this window do not extend
it. Exact-attempt receipt checks prevent reporter-only retries from fabricating
a new observation. This is separate from the TrustTunnel watcher's unchanged
ten-day policy. The observer limits each cycle to twelve logical GitHub reads;
exhaustion/API/rate-limit errors become UNKNOWN. If public API allowance is
insufficient, the existing optional GitHub credential needs only Actions/PR read
access on this repository. Never give the observer write access.

Acknowledgements are saved after each accepted Telegram response. At most three
messages are sent per cycle with spacing; remaining events wait for the next
cycle. Failed delivery is retried next cycle; persistent audit incidents remind
daily. Ambiguous response loss can duplicate a message, and short-lived states
between polls can be missed. No exactly-once or complete historical event claim
is made. A corrupt state/credential causes a visible service failure. Failure of
the monitor host itself still needs another observer/manual checks.

## Activation and owner acceptance

1. Review and merge this PR, verify its full CI, including the real preparation
   fixture. The fixture uses an isolated, explicitly synthetic historical
   `rustls-webpki 0.103.15 -> 0.103.16` case and a changed-notice refusal. It creates
   no PR, release or installation and does not change the normal checkout/pin.
2. Repository **Settings → Actions → General → Workflow permissions**: enable
   **Allow GitHub Actions to create and approve pull requests**. The workflow
   does not approve PRs; GitHub uses this combined setting to permit creation.
   Keep workflow-level permissions as declared rather than making all jobs write.
3. Add Actions repository variable `DEPENDENCY_MAINTENANCE_ENABLED=true`. No new
   server/bot secret is added to GitHub. Dependabot configuration is activated
   from the default branch; check its update logs after the first scheduled run.
4. Run **Dependency maintenance** on main with `dry_run=true`; verify the audit
   summary/artifact and that no branch or PR was created. Then run a new normal
   dispatch with `dry_run=false`, and verify the live receipt and audit result.
   A healthy current lockfile is expected to produce no PR. Do not invent a real
   advisory or downgrade main just to force a write test.
5. On the existing monitoring host, copy the reviewed `scan_dependency_events.py`
   and `notify_dependency_events.py` into `/opt/solartt-upstream-monitor/`, root
   owned, mode 0644. Retain its existing three helper files and credentials.
   Install only the two `solartt-dependency-events.*` units, then verify with
   `systemd-analyze verify` and daemon-reload. Do not restart the bot/VPN or the
   existing Watcher timer. Installation requires the operator's normal sudo path.
6. Before enabling the new timer, use `systemd-run` as in the
   [existing TEST procedure](self-hosted-upstream-monitor.md#controlled-delivery-and-activation)
   with the same three credential mappings, but execute
   `/usr/bin/python3 -B /opt/solartt-upstream-monitor/notify_dependency_events.py --test-cycle`.
   Confirm all three clearly labelled messages in the intended chat/topic. The
   test never creates a real PR and never writes the normal notification state.
7. Start `solartt-dependency-events.service` once, require audit OK, then enable
   `solartt-dependency-events.timer`. Confirm another scheduled execution and
   record the reviewed source commit, workflow URLs and receipt privately.

Synthetic tests and a healthy dry run verify preparation, not live GitHub PR
publication. The first real vulnerability must also establish branch/PR/CI
creation and its delivered notification. Until then mark live publication as
unobserved. A new package release, human acceptance for behavior changes and any
Riga upgrade remain separate, reviewed operational tasks.

References: [RustSec cargo-audit](https://github.com/rustsec/rustsec/tree/main/cargo-audit),
[Cargo conservative updates](https://doc.rust-lang.org/cargo/commands/cargo-update.html),
[workflow dispatch from GITHUB_TOKEN](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
[Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).
