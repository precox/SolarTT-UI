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

## Written, awaiting native CI

Real TLS/H2 tests for revoke A/preserve B across TCP and UDP, closure of A's
UDP socket, mixed-credential rejection, empty-user rejection, payload accounting
across both protocols, and managed destination denial after DNS resolution.

Package smoke test runs only on a disposable GitHub Actions Linux runner. It
covers explicit service startup, authenticated panel/agent IPC, trusted fixture
TLS, SIGHUP renewal without restart, HTTP cover, TLS revocation, backup/restore,
package reinstall and removal with an unrelated SSH service PID unchanged.

These tests have not been compiled/executed locally. Native dependencies require
CMake/libclang and more build capacity than this workspace permits. A prepared
workflow is not evidence of a passing build.

## Still required before a stable v0.1 release

Native/legacy regression CI, official CLI and Android interoperability,
HAProxy passthrough integration, certificate/ACME renewal integration,
clean VM upgrade testing, dependency license review and resource/throughput
measurements. The release checklist remains unchecked where the full requirement
has not been verified.
