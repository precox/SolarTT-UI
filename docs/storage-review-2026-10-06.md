# Stage 1: audit, retention and storage failure — 2026-10-06 UTC

Development version: `0.1.0-alpha.2`. Code commit:
`30904b5a6efa7fd61a61c3c46a0c5f8c7b8294b6`.
All four jobs passed in
[Actions run 37394545941](https://github.com/precox/SolarTT-UI/actions/runs/37394545941).
This is development acceptance, not a production deployment or stable release.

## Delivered

- Profile preparation/denial is durably audited before a secret-bearing reply.
  Events include the checked peer UID, user/profile identifiers and request ID;
  they include no profile material. Known revoked profiles keep their owner ID
  on denied export events. JSON cannot supply a caller UID.
- Audit is bounded by count and age; operation receipts have a count/age replay
  window and a durable revision floor for rejected old retries.
- Quota ledgers are never deleted by retention. New periods are capped, while
  old-period reuse retains old spend. SQLite pages and WAL write admission are
  constrained without changing host filesystem quotas.
- The panel renders audit caller/profile identifiers and storage status. It
  requires audited-export/storage capabilities from the paired agent.
- Schema 1 upgrades transactionally to schema 2 after key, timezone and active
  credential validation. Source-preserving checks and staged restore support
  custom host retention limits. Future schemas remain refused.

Default limits: audit 90 days / 10,000 rows; receipts 7 days / 4,096 rows; quota
history 256 periods per user without deletion; data pages 64 MiB; WAL admission
threshold 16 MiB. Exact behavior, failure boundaries, retry and downgrade rules
are documented in [the storage contract](storage-and-audit.md).

## Verification

137 tests passed:

- 36 portable: 29 policy, 3 control API, 3 panel, 1 profile export.
- 95 upstream library regressions.
- 5 managed transport tests and 1 raw H2-frame regression.

Nine new policy regressions use real SQLite fixtures. They verify secret-free
export audit, durable write gating, rollback of mutation/retention under
`SQLITE_FULL`, failed grant admission, conservative checkpoint/restart, pinned-WAL
reader backpressure, exact/expired replay, retained period spend/caps, and
validated schema migration with atomic failure/retry. Wrong-key validation leaves
the legacy schema unchanged; `check` validates a copy; old-snapshot restore
upgrades staging and preserves charges.

Installed-package checks verified successful/denied export audit against the
actual panel peer UID, storage information and rejection of UID fields supplied
in JSON. The first run stopped because the new test expected HTTP 400; Axum
correctly returns 422 for this schema-invalid JSON. The corrected run passed.
The real browser verified storage status and caller/profile audit columns,
in addition to existing login, creation, issuance, QR clearing, label rendering
and logout checks.

Official CLI, proxy FIN/Caddy PROXY v2, TLS renewal without restart, targeted revoke,
IPC permissions, backup/restore, package reinstall/removal and unrelated SSH PID
checks passed. Real ELF ABI/linkage, payload equivalence, checksum and license
notice checks passed. The explicit release measurement completed but is not a
capacity claim.

Gitleaks source/history and unpacked-package/artifact scans found zero confirmed
secrets. RustSec found zero known production-lockfile vulnerabilities using
database `ef6173cbc5c50ec8166f9a5b28f07834144373ee` (1290 advisories), with the two
unmaintained PEM-parser warnings still visible. Cargo.lock changes are the six
local alpha.2 versions plus the admin utility's existing TOML dependency; there
was no bulk dependency update.

Development artifact `11382372129`, ZIP SHA256:
`aae0d7c6f0242de9a66dc5ad7b0059d2543b5a49961cb61d6fb009a0b78d4816`.
The final documentation commit does not change the verified code or tests.

## Remaining work and deployment boundary

- Preserve a clean schema-1 snapshot/key before future upgrade. Alpha.1 refuses
  schema 2; no in-place downgrade is provided.
- Controlled `SQLITE_FULL` is tested without filling the host disk. Real device
  I/O failures, filesystem exhaustion, power loss, sustained growth and distinct
  version package upgrade/rollback on a fresh VM remain operational gates.
- Managed Android, operational ACME, native advisory/license review, release
  signing/provenance and per-user resource fairness remain open.
- This stage changed repository code/docs and ran private portable fixtures;
  native compilation/package installation used disposable GitHub runners.
  Production services, certificates, DNS, firewall and recovery bundles were
  not changed. Main was not merged and no release was published.

Earlier security/handoff reports describe their historical commits. Their open
export-audit/retention items are superseded by this stage; their other limitations
still apply. The next stage is a reviewed isolated pilot, not automatic deployment
over a working stock endpoint.
