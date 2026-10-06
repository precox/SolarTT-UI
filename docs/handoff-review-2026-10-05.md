# Handoff follow-up review — 2026-10-05 UTC

Historical acceptance record. Export audit, retention and schema migration were
subsequently completed in [alpha.2 stage 1](storage-review-2026-10-06.md).

Reviewed baseline `76cc6a22bbf91842ed7d7246dbd027cf8d7bbe6f` against the operational
handoff. That document provides context and prior measurements; it does not
authorize production deployment. Changes here concern SolarTT source, examples
and disposable-runner verification. Production configuration, services, DNS,
certificates, firewall and recovery bundles were not changed.

## Main finding: shared proxy budget

The reported outage mechanism is consistent with HAProxy's documented half-close
timeouts. The previous package fixture had 60-second normal timeouts and no FIN
directives. It tested routing through an OpenSSL backend, not Caddy's PROXY listener.
Therefore it did not establish protection against accumulation of half-closed
sessions or compatibility of the existing Caddy branch.

Managed agent limits protect its own connections. They do not constrain other
backends sharing HAProxy's frontend budget. The operational fix belongs in the
proxy configuration, independently of dynamic users and quota policy in SolarTT.
No conclusion about the origin or intent of the incident traffic is established.

Changes:

- Added a packaged integration example with long normal timeouts and both FIN30s
  directives. It does not apply itself to any host.
- Added an isolated comparison: absent FIN directives, four half-closed sessions
  remain; with FIN1s, both directions release their two sessions within five seconds.
- Verified one authenticated H2 transport survives both an idle interval longer
  than the FIN clock and repeated live checks during cleanup.
- Replaced the OpenSSL website fixture with checksum-pinned official Caddy 2.11.4.
  It receives PROXY v2 before TLS, echoes the actual original client address and
  rejects an immediate peer outside its restricted allowlist.
- Verified ordinary TLS/H2 reaches TrustTunnel without a PROXY prefix; a prefixed
  attempt cannot complete TLS and is terminated by the bounded server handshake.

The first new run passed FIN cleanup and package inspection, but its negative
TrustTunnel prefix test used a 3-second client deadline against a 10-second server
handshake deadline. It failed before server cleanup. The corrected fixture uses
a 1-second server handshake deadline and still requires a server-side TLS error
or EOF; a client timeout is not accepted as success.

This bounded regression does not reproduce a full production outage or constitute
a fresh production measurement of FIN30s. Protocol compatibility with Caddy is
checked separately from the deliberately holding TCP backends. The official
fixture binary does not certify an operator's custom Caddy build.

See [integration boundaries and rollback considerations](proxy-integration.md).

## Dependency review

Fresh Gitleaks source/history scans found no confirmed secrets. Production
`Cargo.lock` has zero known RustSec vulnerabilities using database commit
`ef6173cbc5c50ec8166f9a5b28f07834144373ee` (1290 advisories). Production versions
include `h2 0.4.19`, `rustls 0.23.45`, `boring/boring-sys 4.22.0`, `quiche 0.24.9`.
The two unmaintained `rustls-pemfile` warnings remain visible.

The original archive's full-workspace lockfile is a separate input with 411
dependencies. Its scan reports RUSTSEC-2026-0258 for `h2 0.3.27` and `0.4.15`, and
RUSTSEC-2026-0285 for `rustls 0.23.43`. It is not the SolarTT production lockfile.
The managed patch now requires Rustls >=0.23.45 in both library and test dependencies,
as it already requires patched H2. The upstream regression resolves these reviewed
minimum changes before compiling. Legacy test-only dependencies and unused upstream
workspace components are not evidence of SolarTT runtime dependency versions.

Primary Rustls advisory:
[RUSTSEC-2026-0285](https://rustsec.org/advisories/RUSTSEC-2026-0285.html).
Do not transfer this managed build's scan result to a prebuilt stock endpoint or
the official CLI binary. Official CLI 1.1.7 remains checksum-pinned and functionally
tested; no claim of a complete advisory audit of its binary is made.

## Package/runtime inspection

Added real package payload and ELF checks, rather than relying on successful
startup on a runner with build dependencies already installed:

- Package SHA256 sums match; `.deb` and tar have identical file payloads.
- No development directories, key files or databases are included.
- Actual NEEDED libraries are `libc.so.6`, `libgcc_s.so.1`, `libm.so.6` for all
  three executables. All resolve on the supported Ubuntu 24.04 runner.
- Maximum required GLIBC versions are 2.38 for agent and 2.34 for panel/admin;
  the declared supported minimum remains Ubuntu 24.04 / libc6 >=2.39.
- The builder derives any optional `libstdc++6` dependency from ELF input and
  rejects unreviewed runtime libraries. This build needs no dynamic C++ runtime.
- `runtime-dependencies.json` records tool/system-package versions and linkage;
  `proxy-regression.json` records proxy checks. Both remain artifact-only reports.

These checks establish ABI/linkage and provenance, not a complete C/C++ or OS
vulnerability assessment. The license collector's notice completeness check also
does not establish all license obligations.

## Verified commit and CI

Code commit `7ec4b1779e20bb3268e704c82a397742e34d81ae` passed all four jobs in
[Actions run 37389703858](https://github.com/precox/SolarTT-UI/actions/runs/37389703858).
127 tests passed: 26 portable, 95 upstream, 5 managed transport and 1 raw H2-frame
regression. The explicit release measurement, new proxy/package checks, installed
IPC, official CLI, browser, TLS reload, targeted revoke, backup/restore, reinstall
and removal checks also passed. Unpacked-package/artifact secret scans found zero
matches. This review's final documentation commit does not change tested code.

Development artifact `11381380437`, ZIP SHA256:
`41c5765b1fde3cd63cfa3140ae97471ae13c65207f060560b5e8f696bbcf38a1`.

## Remaining release requirements

Managed Android interoperability, operational ACME renewal, upgrade between distinct
versions, sustained resource/disk-growth tests, profile-export audit events and
retention policy remain open. Global socket caps do not provide per-user fairness
or protect every proxy route. Release signing/provenance, native advisory and
license review, migrations and independent security review remain required.

SolarTT SQLite snapshots require their matching master key. A stock host recovery
bundle is a different format and does not restore managed policy state. A future
HostVDS integration needs its own reviewed plan and rollback; it must preserve
existing services and avoid stock restart hooks on the managed agent.
