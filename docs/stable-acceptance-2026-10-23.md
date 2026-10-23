# v0.1.0 accepted scope — 23 October 2026

The owner authorized the first stable release with documented limitations.
Network availability was excluded from the release decision. The owner then
explicitly accepted deferral of full independent stack recovery, actual public
certificate replacement and capacity benchmarking, with no advertised capacity
or complete disaster-recovery guarantee. This record does not claim those checks
passed and does not authorize retiring or migrating the production node.

Machine-readable decision: [v0.1.0-acceptance.json](releases/v0.1.0-acceptance.json).

## Runtime basis

The baseline is published `v0.1.0-alpha.6`, source
`aecedf0bd5407e11968cc710d56779b9ce35f7ce`. See its
[scoped owner acceptance](alpha6-acceptance-2026-10-21.md).
v0.1.0 changes version metadata, release tooling and documentation. It does not
change agent/panel runtime logic, policy, schema, dependency versions or the
managed upstream patch. Version strings change binary digests; this is source
equivalence of unchanged behavior, not a claim of identical ELF bytes.

The exact new package must pass its own CI, including published alpha.6 upgrade
and guarded recovery. A version-only release does not repeat unaffected physical
Android flows; the accepted baseline/manual scope remains identified separately.

## Installed alpha.6 observation

On an operator-approved shared Ubuntu 24.04 x86_64 node, 22–23 October:

| Item | Actual result |
| --- | --- |
| Local observation | Completed 24-hour deadline; 1,373 aggregate samples |
| UI and verified TLS/H2 local route checks | 138 checks, 0 failures |
| Collection errors | 0 |
| Agent / panel restarts or OOM | 0 |
| Peak sampled agent / panel RSS | 17.36 / 4.45 MiB |
| Peak agent / panel CPU over a sampling interval | 23.33 / 0.03 percent of one core |
| Fresh matching-key database restore | PASS: separate private DB; schema, document, ledger, audit and retry tables equal |
| ACME staging webroot renewal | PASS; live certificate/key/renewal configuration and service PIDs unchanged |

Those RSS/CPU values describe this window, not minimum server requirements or
maximum capacity. Client payload was not continuous for the whole day. The
observer checked a host-local route to the public frontend; external client
reachability was a separate incident. No raw logs, profiles, keys, databases,
private addresses or real user screenshots are included in this public record.

## Deferred checks and support boundary

- Network reachability/filtering resistance is not a v0.1.0 guarantee. The
  operator observed network-dependent direct-access failures; no particular
  TSPU or other filtering mechanism is asserted as the established cause.
- Full-stack restore on an independent host after loss of the source remains
  unverified. The operator selected same-host backups; successful local DB
  restore does not provide off-host redundancy.
- Actual public ACME certificate replacement and the subsequent live deploy-hook
  reload remain unverified. Staging challenge success is narrower evidence.
- No measured concurrent-user limit, supported throughput/loss envelope or
  production disk-sync capacity is advertised. Planning estimates stay labelled.
- The packaging target is Ubuntu 24.04, Linux x86_64, systemd. Recorded clients
  are CLI 1.1.7 and Android 17 / app 1.2.0 in their listed scoped scenarios.

All ordinary security, license, artifact integrity, transport/policy and package
upgrade CI gates remain mandatory. Network exclusion does not bypass these gates.
