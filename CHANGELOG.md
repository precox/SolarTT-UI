# Changelog

## 0.1.0-alpha.3 — 2026-10-17 (first public alpha)

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
