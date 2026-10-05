# Changelog

## 0.1.0-alpha.1 — unreleased

- Independent Rust agent, browser panel and host administration utility.
- Encrypted per-profile credentials, rotation and revocation.
- Shared bidirectional TCP/UDP payload quota, expiry and calendar periods.
- Durable byte leases, cancellation handling and conservative crash recovery.
- Idempotent mutations, revision acknowledgement and audit history.
- Official deep-link/TOML export with local SVG QR generation.
- Pinned upstream with explicit optional managed-mode patches.
- Development CI, Ubuntu 24.04 package templates and isolated package smoke test.

This is development code, not a verified stable release. See the verification
record and release gates. Native regression, managed transport and isolated
package checks passed in CI; Android and operational pilot checks remain pending.
