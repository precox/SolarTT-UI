# Verification record

2026-10-05, local development workspace, Rust 1.95.0, one build job.
No production endpoint or network configuration was changed.

## Passed locally

```sh
cargo test --locked -p solartt-control-api -p solartt-policy -p solartt-profile-export -p solartt-panel -p solartt-admin --jobs 1
```

25 tests passed: control API 2, policy/calendar/restore 19, panel 3,
profile export 1. Admin operations are exercised through policy library tests.
Formatting checks and Clippy with warnings denied also passed locally.

Coverage includes shared concurrent quotas, partial writes and drop refunds,
unknown cancelled writes, lowered limits across restart, clean shutdown,
period reuse, monthly persistence, DST/month boundaries, caller cancellation,
credential encryption, fail-closed key validation, process locking, future-schema
refusal, WAL snapshots and verified restore. Panel tests cover Host/Origin,
CSRF, session invalidation, secure cookie flags and login throttling. Profile
export roundtrips through the pinned official deep-link codec.

## CI verification

Full workflow passed for commit `29b8de9b8ecd6a0f3e0ccda1cad46a1dcc7ac122`,
[Actions run 37282009229](https://github.com/precox/SolarTT-UI/actions/runs/37282009229).
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
artifact includes their provenance, package checksums and an explicitly invoked
release measurement fixture. The first serial TCP measurement was affected by
Nagle/delayed ACK in the test sockets; a follow-up enables TCP_NODELAY there.
UDP completed 1,000 serial 1,200-byte echoes without loss. The durable 256 KiB
lease grant averaged 0.442 ms including task scheduling. Process RSS was about
17.2 MiB, including the in-process client and echo servers. These values describe
this fixture on this runner, not server capacity or a load test.

## Still required before a stable v0.1 release

Android interoperability with the managed build, browser interaction/security
checks, operational ACME renewal, upgrade between distinct versions, dependency
license obligation review, sustained load/resource limits and measurements on
the intended node. The release checklist remains unchecked where the full requirement
has not been verified.
