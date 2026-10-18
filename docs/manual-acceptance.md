# Preparing isolated human acceptance

Status: **prepared inputs, no persistent environment provisioned or deployed**.
The CI kit does not claim Android, real-network, sustained-load or owner acceptance.
Riga and working-user accounts are outside this procedure.

## When this gate applies

Before publishing an agent or panel behavior change, identify the affected flows
in the PR: login/administration, profile creation/export, policy/device limits,
quota accounting, revocation, transport/reconnect or upgrade/configuration. Have
the owner review those flows on an isolated candidate environment. An unaffected
flow may be deferred with a specific explanation; CI passing does not check the
human-acceptance box automatically.

Maintenance-only changes can prepare this kit without deploying a VM. Record
that distinction in the PR. Deployment, a paid VM, DNS/certificate changes and
production rollout need separate explicit operational authorization.

## Candidate kit and source identity

The `pilot (alpha5)` CI job builds `solartt-manual-acceptance-kit` after its actual
published alpha.5 → candidate package upgrade/rollback/restore passes. Download
it from the exact candidate commit's CI run. Retention is seven days; if expired,
rebuild and recheck that same reviewed source rather than using a moving branch.

Contents are allowlisted public inputs only:

- `identity.json`: exact baseline/candidate source, versions, checksums, CI link,
  `PREPARED_ONLY`, `human_acceptance=NOT_PERFORMED`, `deployment=NOT_PERFORMED`.
- `baseline/`: immutable published alpha.5 deb and its checked build identity.
- `candidate/`: the CI-tested deb and build identity; the version may still equal
  alpha.5 in development, so compare **source commits and package SHA256**, too.
- `alpha5-upgrade-report.json`, this procedure, a blank acceptance record,
  backup/upgrade instructions and example configurations.
- Tracked public Markdown documentation under `docs/` and examples under
  `examples/`; root `README.md` identifies the current entry point. Historical
  verification records remain historical and do not establish this candidate's
  acceptance. Untracked files in those directories are not copied.
- Root `SHA256SUMS` covers all included files with relative paths.

After extracting into a new directory, run `sha256sum --check SHA256SUMS`. Match
candidate source and package digest to the reviewed CI/artifact provenance.
Checksums detect changes; they are not a signature or a substitute for trusting
the reviewed source/run. The kit contains no installer, automatic host commands,
database, credentials, profiles, private keys or diagnostic logs.

## Isolated environment inputs, reviewed before deployment

Select a disposable Ubuntu 24.04 x86_64 VM with an exact deletion deadline,
operator access and a budget. Review the [manual pilot plan](manual-pilot-plan.md)
and [runtime requirements](system-requirements.md). Use a separate hostname,
operator-managed trusted TLS and synthetic expiring A/B accounts. Do not import
production data, certificates, admin hashes or working-user profiles.

Keep panel administration on loopback through an operator-controlled SSH forward;
do not expose the panel or agent metrics publicly. Review firewall/listeners,
service UIDs/peer allowlist, DNS and certificate renewal independently. Example
addresses/domains/UIDs in the kit must be replaced with reviewed test values;
they are not a deployable configuration. Build only in CI, not on the test VM.

Record the environment and intended checks in `manual-acceptance-record.md` before
installation. Public records contain sanitized labels and hashes only; keep
access details, keys, profiles and raw logs in private operator storage.

## Human session

1. Install the exact alpha.5 baseline on the authorized isolated VM, configure
   synthetic A/B accounts, confirm normal access and charge some real traffic.
   Record private baseline state and make a stopped backup with its matching key.
2. Install the exact candidate without auto-start assumptions; follow
   [backup/upgrade](backup-upgrade.md). Verify administrator login, existing user
   policy, device count, quota balance, configuration and saved profiles.
3. Panel changes: inspect the affected desktop/mobile flow with the owner. Check
   form validation, error messages, editing, profile export and logout. Never
   publish a screenshot containing an exported secret or QR profile.
4. Agent changes: record official client/Android/OS versions and named test
   networks. Exercise relevant reconnect/DNS/TLS/expiry/quota flows with synthetic
   accounts. For quota/revoke changes, keep B's established TCP/UDP traffic running
   while A is exhausted/revoked. Record exact results and limitations.
5. Check the specific before/after behavior from the PR, including failure paths.
   Runner H2 durable-lease regressions and historical alpha.1 tests remain mandatory
   and complementary; do not reproduce the known hanging old binary on Riga.
6. If a failure appears, stop acceptance and preserve the current state privately.
   Use the reviewed stopped-snapshot recovery plan. After new traffic/policy
   changes, a stale snapshot cannot safely erase spend; record any reconciliation.
7. Owner records accept/reject/defer with reasons for the exact candidate. PR
   approval, publication and production installation remain separate decisions.

## Teardown

Revoke synthetic credentials, stop the authorized test services, preserve the
sanitized record and private evidence, then delete the isolated VM/DNS under the
operator's procedure. Confirm resource deletion; do not leave a public endpoint
or open-ended paid VM running. This repository performs none of those operations.
