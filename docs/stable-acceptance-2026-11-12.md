# v0.1.1 accepted scope — 12 November 2026

The owner explicitly authorized **stable v0.1.1 publication with documented
limitations** on 12 November 2026, after merging and reviewing the candidate
acceptance and Tokio/Rustix applicability records. This authorization covers the
GitHub release after all publication gates succeed. Installation on a live VPN,
service restart, proxy changes, key rotation and destructive operational tests
remain separate decisions.

Machine-readable decision:
[v0.1.1-acceptance.json](releases/v0.1.1-acceptance.json).
Detailed evidence:
[candidate acceptance](v0.1.1-candidate-acceptance-2026-11-12.md),
[sanitized checks](releases/v0.1.1-candidate-checks.json), and
[dependency advisory review](dependency-advisory-review-2026-11-12.md).

## Tested basis and release delta

The actual test package is published `v0.1.1-alpha.1`, source
`690b621074896cf6758f12ea5ff612f21197d82a`, deb SHA256
`e2e54ee20fa441f50cfe94ff40ee094c9b5a47242ad3a6b1c0ac4356f948f6a4`.
The stable preparation changes version metadata and documentation only; runtime
code, dependencies, schema, configuration defaults and the managed upstream patch
remain unchanged from that tested basis. Version strings change binary digests.

The merged preparation `849ef3d89e7ee426aafbe403a0d841a4b40d85c4` passed
[all nine required CI jobs](https://github.com/precox/SolarTT-UI/actions/runs/43283541414).
The publication-decision revision and eventual stable tag require their own
applicable CI; this earlier run is not evidence about a future tagged binary.

## Accepted results

- Official TrustTunnel Android 1.2.0 / Android 17: owner-confirmed Wi-Fi access,
  automatic Wi-Fi/mobile/Wi-Fi transitions, quota policy recovery and rejection
  of a revoked profile on manual reconnect.
- Synthetic A quota enforcement/revocation preserved original B TCP/DoT and
  UDP/DNS streams: 358 pairs / 1,796.503 seconds, no reconnects. Manual quota
  testing lowered the limit below confirmed spend; natural traffic exhaustion
  and timestamp-injected monthly rollover have separate CI evidence.
- Matching-key local QA backup/restore passed, stale-snapshot rollback was
  refused, the saved B profile worked after restore and revoked A stayed denied.
- The owner accepted a shortened **20 h 39 min** observation instead of the
  planned 24 hours: 1,240 samples, 248 periodic TCP/UDP probes plus a final probe,
  zero health/collection/probe errors, restarts or OOM events. This was light-load,
  loopback-only QA on a shared host, not a full 24-hour or capacity test.
- Real staging DNS-01 issuance and renewal dry-run with a fenced QA reload hook
  passed; fresh verified TLS/H2 and original TCP/UDP continuity passed. The
  deploy hook used the active staging leaf. It was owner-mediated DNS testing.
- Temporary QA identities/processes/state/keys/profiles/listeners and test TXT
  values were removed. Production identity and selected configuration guards
  remained unchanged.

## Owner-accepted limitations

**Deferred, not PASS:** independent full-stack restore after losing the source
host, actual public-certificate replacement, and a capacity benchmark covering
client concurrency, throughput/UDP loss and disk-sync costs. Local database
restore, staging renewal and the shortened low-load observation do not establish
these broader properties. No network-reachability or censorship-resistance
guarantee is offered; compatibility is limited to recorded clients and target.

The [Tokio/Rustix review](dependency-advisory-review-2026-11-12.md) found no
affected execution path in the supported managed mode for the exact reviewed
graph. Warnings remain visible; this does not clear standalone upstream ICMP or
arbitrary future dependency graphs. Patched libraries remain separate maintenance
candidates. No advisory ignore list or dependency update is introduced here.

The exact stable tag must pass every ordinary security, license, transport,
policy, historical-upgrade, package and minimal-runtime gate before publication.
Public assets then require independent download and checksum/content verification.
Owner acceptance of limits does not waive those checks or authorize installation.
