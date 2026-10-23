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


## Existing-node observation checkpoint — 2026-10-15 22:59 UTC

The installed agent and panel still run the exact `86827cd` artifact binaries,
with the same process identities since the 06:58 UTC cutover and no automatic
restarts. At this approximately 16-hour checkpoint, both were ready, storage
writes were healthy, cgroup memory high/max/OOM events were zero and their journals
contained no error-priority entries. Confirmed aggregate payload increased since
the cutover. This is passive operational evidence, not a sustained client-stream,
throughput, loss or 24–72-hour observation test.

Point-in-time RSS was about 18 MiB for the agent and 22 MiB for the panel. The
SQLite main file was 53,248 bytes and WAL 156,592 bytes; a fresh live snapshot passed
the matching-key/timezone check. No user/profile/policy mutation, service restart,
proxy/SSH change, packet test or new CI run was performed for this checkpoint.
Android UI/issuance and network-switch acceptance remain operator checks. The
configured-device-limit count was still zero; existing users retained default 16.

The persistent-pilot template now describes private SSH administration and the
explicit cohosting exception used by the operator pilot. It must not be mistaken
for authorization to create a second deployment or publish an admin hostname.
The release checklist records the tested profile-limit gate while keeping target
load, complete client/network acceptance and license review gates open.


### Notice inventory follow-up

The installed artifact's 297 dependency records were reconciled with Cargo.lock,
and all 548 notice files plus supplemental checksums were verified against the
artifact and installed payload. No gaps were found in this structural inventory.
The [inventory review](dependency-notices.md) preserves the distinction between
file completeness and the still-open license-obligation release gate. No native
build, dependency update or package installation was needed for this check.

## Manual Android server settings — 2026-10-16

Code `379bb44` adds decoded, individually copyable Android server settings to the
Connection profile dialog. Final source/build `b034514c3c41d3639f28b9e19036475efefa8f9c`
includes the browser assertion correction. The manual card is primary; link/QR and
TOML remain under Other export formats for compatible clients. This does not
claim that a particular Android app supports profile import.

The panel parses the existing audited TOML response into typed fields, preserving
quoted/escaped credentials as their decoded values. It never reads credentials a
second time or changes the agent protocol. Unsupported trust/protocol settings
produce generic errors without echoing the export. The password starts hidden;
close clears all manual fields, export data and visibility state. Copy failure
keeps the password hidden and offers explicit manual selection. Clipboard content
is outside dialog clearing, as described in client-compatibility.md.

[CI run 38871492066](https://github.com/precox/SolarTT-UI/actions/runs/38871492066)
passed all five jobs: security, portable, native, legacy and pilot. There are
150 functional tests (49 portable, 6 managed, 95 upstream), plus the separately
invoked release measurement and package/browser/upgrade scenarios. New panel tests
verify exact TOML decoding and generic rejection without secret disclosure. The
browser fixture verifies field mapping, copying each nonempty field, clipboard
rejection, explicit password visibility, clearing between three issuances, and
modal fit/touch controls at 320/390/1280 px. Existing device-limit and quota-value
preservation checks remain enabled. The initial run 38870769981 failed because a
new browser assertion embedded a literal newline in evaluated source; b034514
uses String.fromCharCode(10), and final browser/package checks pass.

Artifact 12033309523, ZIP SHA-256
`ef3172ad897d05dc9547fac36d8fcf462907fd2ca0b953ae0f24e81fe438e4e8`,
was verified against the Actions digest, internal SHA256SUMS, upstream pin,
Cargo.lock and patch hashes. Maintainer scripts and systemd units match reviewed
source; units match the installed ones; ELF libraries resolve. Agent and admin
ELF hashes are unchanged from the previous pilot. Only the panel ELF differs:
`a0813d28e6012a9946f397dc13e39151ad3ba4af353526bbf73a01ba1583ddff`.

The approved existing pilot was updated on 2026-10-16; only the panel was restarted
at 08:13:36 UTC. Authenticated login/info/users/logout, exact embedded HTML/JS/CSS,
private no-store UI, verified TLS/H2 and public cover 200/API-login 404 passed.
A first immediate HTTP check raced the Type=simple listener startup and received
connection refused; a bounded readiness wait and authenticated checks then passed,
with NRestarts=0. The agent PID/start time and running ELF are unchanged. Protected
configuration, key/admin-hash file contents and permissions, canonical policy and
credential document are unchanged; quota accounting is preserved. A fresh SQLite
backup was validated with its matching key/timezone/schema/revision. No live
profile export, new credentials, quota/revoke/rotation or owner-device actions
were performed for acceptance. Real manual entry on the user's Android device
remains NOT VERIFIED; CI browser results do not substitute for it.

## Browser session/issuance fixes — 2026-10-17

Independent Sol 6.1 xhigh review identified two P2 issues: a new pending-issuance
key could be discarded after an unknown result followed by HTTP 401/403; an
inherited late-export response could reopen secrets after session invalidation.
The follow-up review also found an initial-session discovery race that could
restore the login form or old CSRF state after a newer sign-in. All three are
fixed in `19b61b49d641f44e4f317ec0f7ea22319cb1099d`; the same reviewer checked the
final diff and 11 passing standalone tests and reported no remaining blockers.

The panel preserves the original issuance request across HTTP/authentication
errors and sign-out in the current tab. CSRF rejection offers sign-in without
reloading. An expired receipt remains pending with reconciliation guidance.
Session generations guard responses before/after JSON parsing, command handling,
initial session discovery and profile display. Clearing a profile invalidates its
pending export; network failure from an old session cannot retry in a new one.
In-memory retry state is not persisted across reload/tab closure. See the storage
and audit document for this boundary and the required reconciliation.

All 11 pure JavaScript state regressions passed locally and in portable CI. Four
focused regressions were also run against the original source: all four failed,
confirming they detect the reviewed defects. The final
[CI run 39019425992](https://github.com/precox/SolarTT-UI/actions/runs/39019425992)
passed all five jobs: security, portable, native, legacy and pilot. Existing 150
Rust functional tests remain green in addition to the 11 new JavaScript tests.
The disposable installed browser fixture commits a real credential, substitutes a
503 after its response, obtains a real CSRF 403 using a bad token, signs in, then
obtains a real 401 after server-side logout and signs in again. All four creation
attempts use one request ID and resolve to exactly one profile. A real audited
export response held across session expiry cannot restore fields/QR or open a
dialog over login. Package lifecycle and upgrade/rollback/recovery also pass.

Artifact 12095513779 ZIP SHA-256
`2f006517090b5db9a6daaf84d4bc1b54cfc6a72c0cb2cc40afb6aab241b5b619`
was checked against the Actions digest, internal checksums, pin/lock/patch hashes,
reviewed maintainer scripts, unchanged systemd units and local ELF libraries.
Agent/admin binaries are byte-identical to the previous deployment. New panel SHA
is `7fdadcf6d20c30144f8b91848c678eb7d5521679c6e5de76587e22a8af9a7553`.

The existing approved pilot was updated at 09:06:05 UTC with only a panel restart.
Installed/running binaries match the artifact. Authenticated login/info/users/
logout and exact HTML/JS/CSS checks pass. Canonical policy/credentials, protected
configuration/key/admin-hash contents and permissions are unchanged, and quota
accounting is preserved. A fresh SQLite backup passes key/timezone/schema/revision
validation. The agent PID/start time and other service PIDs match the immediate
installation baseline. Verified TLS/H2, private no-store UI and public cover
200/API-login 404 pass. No owner profiles or policies were created/exported/
revoked/reset for acceptance on this host; failure injection took place only in
the isolated fixture. These checks do not establish actual Android acceptance or
continuous production-stream preservation.

## v0.1.0 release decision — 2026-10-23

Historical entries above retain their original test scope. The owner approved
v0.1.0 with explicit verification limits, recorded in
[stable acceptance](stable-acceptance-2026-10-23.md). The installed alpha.6
24-hour observation completed: 1,373 samples, 138 local health checks, zero
health/collection failures, restarts or OOMs. A matching-key local database
restore and ACME staging dry run passed. These results do not establish direct
client reachability, full-stack off-host recovery, actual certificate replacement
or maximum capacity. The release candidate changes no runtime behavior or
external dependencies; its new version and release tooling require fresh CI,
including real package upgrades from alpha.1, alpha.5 and alpha.6. Tagged CI and
exact-source reports are attached to the release; this historical document does
not anticipate their outcome.
