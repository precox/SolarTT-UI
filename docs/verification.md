# Verification record

2026-10-05, local development workspace, Rust 1.95.0, one build job.
No production endpoint or network configuration was changed.

## Passed locally

```sh
cargo test --locked -p solartt-control-api -p solartt-policy -p solartt-profile-export -p solartt-panel -p solartt-admin --jobs 1
```

Initial 25 tests passed: control API 2, policy/calendar/restore 19, panel 3,
profile export 1. Admin operations are exercised through policy library tests.
Formatting checks and Clippy with warnings denied also passed locally. The
updated policy suite later passed all 20 tests, including separate live sessions
sharing one quota and atomic schema initialization.

Coverage includes shared concurrent quotas, partial writes and drop refunds,
unknown cancelled writes, lowered limits across restart, clean shutdown,
period reuse, monthly persistence, DST/month boundaries, caller cancellation,
credential encryption, fail-closed key validation, process locking, future-schema
refusal, WAL snapshots and verified restore. Panel tests cover Host/Origin,
CSRF, session invalidation, secure cookie flags and login throttling. Profile
export roundtrips through the pinned official deep-link codec.

## CI verification

Full workflow passed for commit `6f42ef3291ba82692d513da4c6299db3f4663137`,
[Actions run 37284404437](https://github.com/precox/SolarTT-UI/actions/runs/37284404437).
It passed 26 portable tests, four managed transport tests and 92 upstream tests.
The additional calendar test prevents a manually selected future month from
blocking automatic rollover or refunding its consumed allowance.

Four real TLS/H2 tests cover:
revoke A/preserve B across TCP and UDP, closure of A's UDP socket, credential
rotation and expiry, mixed-credential and empty-user rejection, payload accounting
across both protocols, and destination denial after DNS resolution.

92 patched upstream library tests passed with the upstream lockfile in Actions
run 37280483564 and subsequent runs. The regression suite covers legacy paths.
Release compilation and .deb/.tar.gz generation also passed.

## Package acceptance passed on the runner

Package smoke test runs only on a disposable GitHub Actions Linux runner. It
covers explicit service startup, authenticated panel/agent IPC, trusted fixture
TLS, two SNI routes through HAProxy, official CLI 1.1.7 HTTPS forwarding,
SIGHUP renewal without restart, HTTP cover, TLS revocation, backup/restore,
package reinstall and removal with an unrelated SSH service PID unchanged.

Native checks run on GitHub Ubuntu 24.04 x86_64 workers. No native compilation
or package installation has been performed on the production server. Package
smoke tests exposed and helped fix AF_NETLINK access required by getifaddrs()
and the Python fixture's CONNECT header validation. All package assertions
passed in the recorded full workflow. This is a development artifact, not a
production installation or stable release.

297 dependency notice sets were collected without missing files/metadata. The
artifact includes their provenance, package checksums, a screenshot containing
synthetic fixture users only, and an explicitly invoked release measurement.
After enabling TCP_NODELAY on the fixture sockets, run 37283787988 measured:

- 32 MiB upload echoed back: 131 MiB/s combined bidirectional payload on loopback.
- Process CPU time for that exchange: 0.645 s; two runtime workers.
- 1,000 serial 1,200-byte UDP echoes: no loss, 0.144 s total.
- Durable 256 KiB lease admission: 0.440 ms mean, including task scheduling.
- Process RSS: 17.25 MiB, including the client and both echo servers.

These values describe this fixture on this runner, not server capacity or a
sustained load test. The first TCP sample used Nagle-enabled test sockets and
is not used for throughput conclusions. Raw samples are retained in the artifact.

The installed panel also passed real headless Chrome checks: login, creating a
user, issuing and exporting its credential, local QR, clearing exported secrets,
rendering an HTML-looking label as text, and logout. IPC checks deny unrelated
filesystem users and unlisted peer UIDs; the panel account cannot read the agent's
master key or TLS private key. No real credentials are used in these fixtures.

## Still required before a stable v0.1 release

Android interoperability with the managed build, operational ACME renewal,
dependency license obligation review, sustained load/resource limits and measurements on
the intended node. The release checklist remains unchecked where the full requirement
has not been verified.

## Security review follow-up — 2026-10-05

Code commit `78520563ce178f64d81fc5f84424a6baf90af228` passed all four jobs in
[run 37306928493](https://github.com/precox/SolarTT-UI/actions/runs/37306928493).
It upgrades production H2 to 0.4.19, adds bounded managed outbound resources
and service memory/task/file-descriptor containment, and scrubs two malformed
request diagnostics. The 127 passing tests comprise 26 portable, 95 upstream,
5 managed transport and 1 raw-frame denial-of-service regression. The original
upstream lockfile is minimally resolved for the reviewed h2 dependency upgrade
before its library tests; production uses the committed root lockfile.

The security job scanned full Git history and tracked source with Gitleaks and
found zero confirmed secrets. RustSec found zero known vulnerabilities in the
production lockfile, with visible unmaintained-parser warnings. Native acceptance
again passed official CLI, browser, HAProxy/TLS, installed IPC and package lifecycle
checks. Both unpacked packages and the artifact directory passed secret scans.
See [the security review](security-review-2026-10-05.md) for methods and residual
risks. Development artifact 11344456785 belongs to this code commit.

## Operational handoff follow-up

Code `7ec4b1779e20bb3268e704c82a397742e34d81ae` passed all four jobs in
[run 37389703858](https://github.com/precox/SolarTT-UI/actions/runs/37389703858).
All 127 tests still pass, with additional package assertions for both half-close
directions, a no-FIN control, preserved idle/live H2, actual Caddy PROXY v2,
untrusted-peer rejection, TrustTunnel prefix refusal and real package ELF/linkage.
The managed patch requires patched Rustls >=0.23.45. Package/artifact secret scans
again pass. See [the follow-up report](handoff-review-2026-10-05.md) for scope,
original upstream-lock findings, artifact digest and remaining requirements.

## Alpha.2 storage and audit

Code `30904b5a6efa7fd61a61c3c46a0c5f8c7b8294b6` passed all four jobs in
[run 37394545941](https://github.com/precox/SolarTT-UI/actions/runs/37394545941).
137 tests, installed export-audit/UID checks, real browser storage/audit rendering
and existing native/package checks passed. Source/package secret scans and the
production dependency gate passed. See [stage 1 evidence](storage-review-2026-10-06.md)
and [the storage contract](storage-and-audit.md) for defaults, schema migration,
retry windows, rollback and remaining operational tests.

## Actual version upgrade and recovery pilot

Code `47b24b713a50f08e020e3a8143d2c69a493f56e8` passed all five jobs in
[run 37516135465](https://github.com/precox/SolarTT-UI/actions/runs/37516135465).
139 functional tests passed: 38 portable, 95 patched upstream, 5 managed
transport and 1 raw-H2 regression. The separate release measurement, installed
package acceptance and browser assertions also passed.

On a fresh GitHub Ubuntu 24.04 VM, the new pilot installed the actual pinned
alpha.1 package, forwarded official CLI TCP HTTPS and UDP/DNS payload, upgraded
to alpha.2, performed a compatible schema-1 rollback and recovered schema 2.
It verified preserved identity/policy/quota, refused active-database and
new-spend rollback, rejected wrong-key/corrupt/overwrite restores, and retained
data after package removal with an unrelated running service unchanged.

History/source and both jobs' package/artifact secret scans reported zero
findings. RustSec reported zero known production-lockfile vulnerabilities;
the two unmaintained `rustls-pemfile` warnings remain. See
[stage 2 evidence and artifact digests](pilot-review-2026-10-06.md),
[the rollback contract](isolated-pilot.md) and
[the persistent manual pilot plan](manual-pilot-plan.md).
