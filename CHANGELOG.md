# Changelog

## 0.1.0 — 2026-10-23

- First stable single-node release for Ubuntu 24.04 x86_64/systemd, based on the
  accepted alpha.6 runtime. No runtime logic, dependency or schema change.
- Record 24-hour local observation: 1,373 samples, 138 UI/TLS checks, no collection
  failures, service restarts or OOM; matching-key database restore and ACME
  staging renewal passed.
- Add guarded stable publication and a pinned published alpha.6 upgrade/recovery
  VM leg alongside alpha.1 and alpha.5. Alpha publication remains prerelease.
- Publish the owner's accepted limitations: no network-reachability or censorship
  guarantee, no advertised client capacity, no verified full off-host stack
  recovery or actual future public certificate replacement.

See [release notes](docs/releases/v0.1.0.md) and the
[accepted scope](docs/stable-acceptance-2026-10-23.md). Publication does not install
this package on an existing node or retire its services.

## 0.1.0-alpha.6 — 2026-10-21

- Fix managed H2 listener timeout closing existing TCP/UDP pipes while waiting
  for a new CONNECT. Empty transports still expire; quota, expiry and revocation
  retain immediate session cleanup. Production configuration defaults are unchanged.
- Add accelerated real TLS/H2 regressions for active A/B flows, scoped revocation
  after the listener deadline and idle/completed-request cleanup. CI reconstructs
  the previous implementation to prove failure before the fix.
- Update rustls-webpki from 0.103.15 to 0.103.16 for RUSTSEC-2026-0382;
  retain the exact dependency notice review.
- Add stable TrustTunnel release discovery, daily RustSec auditing, conservative
  dependency proposal PRs and optional external notification/health monitors.
  Discovery and proposals do not install packages or replace a running agent.
- Require upgrade/guarded recovery from the published alpha.5 package alongside
  the historical alpha.1 pilot; prepare a separate human-acceptance kit.
- Update pinned GitHub Actions and add README mobile previews with synthetic data.
- Record scoped Android Wi-Fi/mobile recovery, 979.3-second original TCP/UDP
  forwarding and isolated revocation acceptance. The temporary test frontend's
  initial connection cap was corrected and recorded; no production rollout ran.

Tagged publication and production rollout remain separate operations. Check
GitHub Releases for available assets; this source entry alone does not authorize
upgrading an existing node. See [release notes](docs/releases/v0.1.0-alpha.6.md).

## 0.1.0-alpha.5 — 2026-10-17

- Fix a managed H2 download stall when a traffic-accounting lease splits a
  response buffer after the sink has consumed all requested flow-control capacity.
  Quota-only tails now request new capacity; actual sink backpressure still waits.
- Add a real one-way 1-MiB TLS/H2 download regression for limited and unlimited
  users, with CI proving failure before the fix and success after it.
- Document the Android client's separate application/core logging levels.

## 0.1.0-alpha.4 — 2026-10-17

- Uses a GitHub-safe deb filename while preserving internal Debian prerelease ordering.
- Rejects asset name normalization before publication; regression verifies equal bytes with a changed name still fail.
- Corrects download URLs/checksum filenames and withdraws alpha.3 without moving its tag or overwriting its assets.
- No runtime behavior changes from alpha.3; all publication gates are rerun.

## 0.1.0-alpha.3 — 2026-10-17 (withdrawn)

- Publishes the existing managed endpoint and mobile panel as a GitHub prerelease.
- Includes user quotas/expiry, individual profiles and admin-set profile limits.
- Manual Android setup fields; safe pending issuance and stale-response handling.
- Ubuntu amd64 deb/tar, source archive, checksums and source/upstream provenance.
- Redistribution review with pinned notices and legacy crypto acknowledgments.
- Minimal Ubuntu runtime acceptance without a compiler, separate from systemd VM tests.
- Private SSH administration instructions and explicit alpha/stable boundaries.

Existing schema-2 development users must back up before upgrading. Alpha.1
cannot read schema 2 or newly serialized device-limit policy fields; follow
[guarded upgrade/restore](docs/backup-upgrade.md). Android/network/capacity and
operational recovery acceptance remain for the stable iteration.

## 0.1.0-alpha.2 — internal development baseline

- Durably audited profile preparation/denial with trusted peer UID and secret-free metadata.
- Count/age retention for audit and retry records; expired retries fail without reapplying policy.
- Preserved quota history with bounded period creation, SQLite page and WAL admission limits.
- Storage status and caller/profile identifiers in the panel.
- Schema-1 to schema-2 migration after key/credential validation; readonly staging checks.
- SQLite-full, checkpoint/restart, pinned-reader, retry and migration regressions.
- Per-user issued-profile limits, mobile device cards and copyable manual Android settings.
- Pending issuance IDs survive reauthentication; stale session/export responses cannot restore secrets.
- Session/CSRF recovery and delayed-response regressions in JavaScript and the installed browser fixture.

See [storage and audit semantics](docs/storage-and-audit.md). Preserve a compatible
snapshot before upgrading; alpha.1 cannot read schema 2. This is development code.

## 0.1.0-alpha.1 — internal development baseline

- Independent Rust agent, browser panel and host administration utility.
- Encrypted per-profile credentials, rotation and revocation.
- Shared bidirectional TCP/UDP payload quota, expiry and calendar periods.
- Durable byte leases, cancellation handling and conservative crash recovery.
- Idempotent mutations, revision acknowledgement and audit history.
- Official deep-link/TOML export with local SVG QR generation.
- Pinned upstream with explicit optional managed-mode patches.
- Development CI, Ubuntu 24.04 package templates and isolated package smoke test.
- H2 0.4.19 security update with a raw empty-frame flood regression.
- Bounded managed outbound TCP/UDP sockets and UDP flows; service resource containment.
- Full-history/source/package secret scans and a RustSec dependency gate.
- HAProxy FIN integration example, half-close controls and actual Caddy PROXY v2 tests.
- Package payload/checksum comparison and real ELF runtime dependency inspection.
- Safe minimum Rustls version enforced in the managed upstream patch.

This is development code, not a verified stable release. See the verification
record and release gates. Native regression, managed transport and isolated
package checks passed in CI; Android and operational pilot checks remain pending.
