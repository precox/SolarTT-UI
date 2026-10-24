# Release publication and stable acceptance

## First public alpha: required publication gates

The tagged release workflow must pass all six prerequisites before it can publish:
source/history/RustSec security scan; portable Rust and JavaScript tests; native
transport/browser/package acceptance; upstream regressions; actual systemd VM
upgrade/guarded recovery; and minimal Ubuntu runtime without build tools.

The pilot gate requires four matrix legs on separate disposable VMs: historical
alpha.1 migration and published alpha.5, alpha.6 and v0.1.0 packages → exact candidate. No
leg replaces the H2 pre-fix/fixed proof or quota/revocation isolation regressions.

Additional release guards require a unique canonical alpha or stable version/tag on `main`, exact
source/build identity, the 297-package redistribution review and 548 notice
hashes, SHA256SUMS for all published assets, private vulnerability reporting,
and complete install/manual Android/private SSH instructions. Publication creates
a draft, uploads verified assets, then marks it as the requested release channel. Attached
`release-tests.json`, `build.json`, `minimal-runtime.json`, `pilot-report.json`
`alpha5-upgrade-report.json`, `alpha6-upgrade-report.json` and `stable-upgrade-report.json`
record the actual results. The container report is not systemd VM evidence.

These gates authorize the experimental alpha; they do not close the field
acceptance items below. Alpha.1/alpha.2 were internal development baselines.

Agent/panel behavior changes also require scoped owner acceptance using the
[prepared kit and record](manual-acceptance.md). CI kit creation leaves human
acceptance unperformed; it does not provision a persistent test environment.

The [alpha.6 scoped owner record](alpha6-acceptance-2026-10-21.md) identifies the
tested package/runtime, Android network switching, long original TCP/UDP and
scoped revoke results, including the corrected test-frontend connection cap.
It does not establish every stable field gate or authorize a production upgrade.

## Stable: existing engineering evidence and remaining work

- [x] Selected official clients recorded: CLI 1.1.7; Android app 1.2.0 on Android 17. This is not all-client compatibility.
- [x] Revoke A closes every TLS/TCP/UDP session; B's long streams survive.
- [x] Mixed principals cannot share one managed H2 transport.
- [x] Empty users reject VPN access, including `_check`.
- [x] All devices and directions share one quota; partial writes and races cannot multiply it.
- [x] UDP whole-packet admission, drop refund and resource cleanup.
- [x] Credential rotation and expiry stop the intended sessions.
- [x] Quota survives crashes; uncertainty is bounded and documented.
- [x] Calendar periods, manual resets, limit changes and timezone behavior tested.
- [x] Private destinations, metadata, local/own IPs and DNS results denied.
- [x] Panel login, rate limits, CSRF, XSS, secret exports and UDS permissions tested.
- [x] Per-user device profile limits enforced in the agent; lower-limit refusal, concurrent issuance and revoked-slot reuse tested.
- [x] Database migrations, backup, guarded rollback and restore tested.
- [x] Fresh GitHub-hosted VM install/upgrade/uninstall preserves an active unrelated service.
- [x] CA verification, SNI passthrough, cover HTTP and TLS renewal tested.
- [x] Isolated HAProxy FIN cleanup preserves H2; actual Caddy PROXY v2 boundary tested.
- [x] Release package payload/checksums and actual ELF runtime ABI/linkage checked.
- [ ] Measured CPU/RSS, TCP throughput, UDP loss and disk sync costs.
- [x] Exact dependency choices/notices and reconstructable upstream pin recorded; publication verifies CI and asset checksums.
- [x] Full Git history, tracked source and unpacked release packages scanned for secrets.
- [x] Production lockfile has no known RustSec vulnerabilities; parser maintenance warnings recorded.
- [x] Export audit, retained retry/ledger semantics and SQLite-full rollback tested.

Unchecked gates are not implemented or verified guarantees. This file is updated
with concrete test commands and results, not with anticipated outcomes.

Automated results: [verification record](verification.md). Checked transport and
policy gates refer to isolated tests on the runner; they do not claim Android,
ACME or production-node acceptance. Database checks cover schema-1 to schema-2
migration, full-storage rollback, future-schema refusal and verified restore.
The [isolated upgrade pilot](pilot-review-2026-10-06.md) also verifies actual
alpha.1/alpha.2 packages, stopped-database rollback without lost quota charges,
recovery with live payload and preservation of an active unrelated sentinel.
The package/upgrade VM contains SDK/build tools. A separate minimal Ubuntu
container checks runtime operation without them; it does not establish persistent
minimal-VM, Android, operational ACME or sustained-load acceptance.

## Remaining field work after v0.1.0

- Record Android app/OS versions and actual manual setup across Wi-Fi/mobile,
  switching and reconnects; verify public IPv4, DNS and IPv6-off behavior.
- On an explicitly coordinated test account, exercise real-network quota, expiry
  and revocation for A while B maintains a long TCP/UDP stream.
- Observe representative workload for 24–72 h: CPU, RSS, socket/FD counts,
  throughput/UDP loss, log/SQLite growth and memory pressure. No mandatory two-week
  wait or advertised users-per-node estimate follows from this alpha.
- Validate an actual future ACME certificate replacement and an independent
  off-host restore with matching key, without resetting committed quota usage.
- Triage alpha feedback; decide stable supported versions and measured sizing.

Do not conduct disruptive tests on owner profiles merely to fill these boxes.

Device-limit and mobile-card evidence is in [the 2026-10-15 verification record](verification.md).
That limit counts non-revoked credentials, including offline profiles; copying
one profile to several devices still uses one slot. Mobile viewport tests do not
establish physical-device identity or replace Android/client network acceptance.

## v0.1.0 owner decision, 2026-10-23

The owner explicitly approved publication with the limitations in
[the stable acceptance record](stable-acceptance-2026-10-23.md) and
[versioned machine-readable decision](releases/v0.1.0-acceptance.json).
The 24-hour installed alpha.6 observation completed with 1,373 samples and
138 local health checks, no collection/health failures, restarts or OOMs.
A matching-key local database restore and ACME staging renewal dry run passed.
The candidate changes version metadata, release tooling and documentation, with
no agent/panel behavior or dependency changes from that observed runtime.

**Deferred, not PASS:** a capacity benchmark (throughput, UDP loss and disk costs),
independent full-stack restore on another host, and actual public-certificate
replacement. CPU/RSS point/observation values do not close the capacity gate.
Direct network availability is outside the release guarantee; no censorship
resistance is claimed. These limits are public in README and release notes.
The complete exact-candidate CI and all artifact/security checks still apply.
