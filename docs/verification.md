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

## Packaging fix and existing-node process evidence — 2026-10-11

Source `72ec312bfb014637e0b65912f251870506d87cd2` passed all five jobs in
[run38154977805](https://github.com/precox/SolarTT-UI/actions/runs/38154977805):
139 functional tests, actual umask077 package build/verification, installed
browser/IPC/package lifecycle and version upgrade/rollback/recovery acceptance.
Secret scans found0 findings and RustSec0 known production vulnerabilities,
with the same two visible parser-maintenance warnings.

Separately, checksum-verified candidate ELF passed17 process checkpoints on an
existing1-vCPU/2-GiB Ubuntu node, including sandboxed browser, real IPv4 CLI TCP,
UDP/DNS and an established public B payload stream surviving A revocation.
Targeted shared-ledger and restored-payload checks also passed. A private24h
observation has started, not completed. See
[the process/CI report](process-pilot-review-2026-10-11.md) for exact artifacts,
RSS, conservative live-snapshot charge and environment distinctions.


## Connection labels and TLS dependency refresh — 2026-10-14

UI commit `a45657f8c261084dd9fed30339fb8496be8b2376` replaces the prominent
session total with connected profiles and labels the secondary table value
TLS connections. A connected profile has at least one live authenticated TLS
transport. This is not a physical-device count or a fixed transports-per-device
ratio. Configurable device limits are not implemented.

The first source audit found four newly published rustls advisories:
RUSTSEC-2026-0346, -0347, -0348 and -0349. Commit
`78dacb7f7ec65c14608e6cfea1256f1f00a2bd57` raises the patched upstream minimum
and production lockfile to rustls 0.23.46. Registry dependency and feature metadata
for 0.23.45 and 0.23.46 matched; the lockfile checksum came from the registry index.
Locked builds and regression tests passed in CI.

[Run 38629127109](https://github.com/precox/SolarTT-UI/actions/runs/38629127109)
passed all five jobs: 139 functional tests, package/browser acceptance, the pinned
alpha.1 upgrade/rollback/recovery pilot, and source/artifact secret checks. The
production dependency audit reported zero known vulnerabilities; existing
rustls-pemfile maintenance warnings remain visible. Its first native attempt timed
out waiting 15 seconds for Chrome's debugger, before dashboard navigation. Rerunning
failed jobs passed without code changes or weakened guards; the initial failure
remains part of the run record.

Development artifact `11925713199` has ZIP SHA-256
`0f52a1eda4a30b1d6afbbd81dea13ab30a1b374e061957055a0e161ad9e3d424`.
The existing operator pilot received this package after digest, payload metadata,
maintainer-script and linkage checks. Only the panel restarted. Live login,
info/users/logout, embedded asset equality, agent readiness, loopback listeners,
public cover TLS and preserved configuration/key hashes passed. The VPN agent
kept its previous process and executable; the new agent binary is installed on
disk but its rustls fix is **not yet applied to the running endpoint**. A later
agent restart requires an agreed interruption window. No device-limit feature,
production quota/revoke exercise or stable-release claim is implied by this update.


## Device profile limits and mobile provisioning — 2026-10-15

Code `86827cd3edf4a5861add7915d85dff9621fd0b46` passed all five jobs in
[run 38635048489](https://github.com/precox/SolarTT-UI/actions/runs/38635048489).
148 functional tests passed: 47 portable (5 control, 3 panel, 38 policy and
1 profile export), 95 patched upstream and 6 native transport/frame tests.
The new policy cases cover issuance limits independent of TLS counts, lower-limit
refusal, zero/range bounds, concurrent last-slot issuance, revoked-slot reuse,
restart/restore, older edit requests and refusal to reactivate revoked profiles
by rotating their credentials. A strict pre-feature policy decoder rejects an
explicit new field rather than silently discarding the restriction.

The package's real-browser scenario exercises mobile cards at 320/390 px and
desktop at 1280 px, creation/export, direct API limit denial, raising the limit,
revocation/replacement, XSS labels, clearing QR/link/app href, and logout. A lost
response after successful creation is simulated; retrying the same request must
return the original profile, not issue a duplicate. A browser failure in the
preceding run exposed a real stored-byte-quota/number-step mismatch. The fix uses
step=any and asserts that editing the device limit preserves the exact byte quota.
Chrome startup now has a bounded 45-second wait; CI-only guards and all functional
assertions remain in place. Package lifecycle, upgrade/rollback/recovery and
source/artifact secret scans passed; the production dependency audit is clean.

Artifact `11926839282` ZIP SHA-256:
`3cb258dc5c605973028e1ee0725488d531a84edd1acffb9b5c1f161e7303d705`.
The operator pilot received the verified package after a fresh live snapshot and
a checked clean snapshot during cutover. Agent and panel now both run its exact
binaries, including rustls 0.23.46. Existing policy/credential digests, revision,
configuration, data key and admin hash were preserved; confirmed usage did not
decrease. Other VPN/front-end/SSH services retained their recorded processes.
Live login/info/users/logout, capability, embedded HTML/JS/CSS equality, loopback
listeners, trusted TLS/H2 and both public covers passed. The first login probe
exceeded 15 seconds while the node was busy; a later probe with a 45-second client
timeout passed. CPU contention was observed, with no OOM or changed resource caps.
This is a pilot update, not a stable release or an Android-device/anti-copy test.
No production user was created, revoked or quota-limited by the acceptance checks.
