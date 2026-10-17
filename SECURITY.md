# Security

SolarTT-UI v0.1.0-alpha.4 is experimental. No supported stable version exists.
Keep administration private and retain a tested backup before a pilot upgrade.

## Reporting a vulnerability

Use [GitHub's private vulnerability report form](https://github.com/precox/SolarTT-UI/security/advisories/new).
Do not put exploitable details, credentials, profile exports, keys, database files
or raw user logs in public issues. A sanitized ordinary bug report can be filed
in Issues. The maintainer reviews reports on a best-effort basis; there is no
response-time SLA for this alpha. Check the repository reporting form before
sending confidential material; publication requires private reporting enabled.

## Boundaries

Root and the host administrator are trusted. The panel cannot execute shell
commands, edit firewall rules or access arbitrary files. The managed agent owns
the credential encryption key and restricted Unix control socket; the panel
receives audited profile exports only. Exports remain secrets even when encoded
as a link, QR or TOML. Do not send them to external QR services.

Per-user issued-profile limits do not identify physical devices or prevent a
profile being copied. Payload quotas are not network-billing quotas. A cover
page and an inconspicuous hostname do not establish censorship resistance.

CI scans full Git history, tracked source and unpacked release artifacts and
checks RustSec advisories. These are bounded engineering checks, not a guarantee
that no vulnerabilities exist. See [release gates](docs/release-gates.md),
[engineering review](docs/security-review-2026-10-05.md) and
[storage/audit semantics](docs/storage-and-audit.md).
