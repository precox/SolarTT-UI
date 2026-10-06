# Changelog

## 0.1.0-alpha.2 — unreleased

- Durably audited profile preparation/denial with trusted peer UID and secret-free metadata.
- Count/age retention for audit and retry records; expired retries fail without reapplying policy.
- Preserved quota history with bounded period creation, SQLite page and WAL admission limits.
- Storage status and caller/profile identifiers in the panel.
- Schema-1 to schema-2 migration after key/credential validation; readonly staging checks.
- SQLite-full, checkpoint/restart, pinned-reader, retry and migration regressions.

See [storage and audit semantics](docs/storage-and-audit.md). Preserve a compatible
snapshot before upgrading; alpha.1 cannot read schema 2. This is development code.

## 0.1.0-alpha.1 — unreleased

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
