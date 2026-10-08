# Persistent manual pilot plan — review before deployment

Use a dedicated disposable VM. Do not install over an existing VPN/site node or
reuse a stock endpoint's certificate restart hook for the managed agent.

## Inputs and sizing

- Ubuntu 24.04 LTS x86_64; small-pilot planning target 2 vCPU / 2 GiB RAM /
  20–30 GiB SSD on a lightly loaded node. The initial 4-GiB proposal adds headroom
  for shared workloads; see [requirements and sizing](system-requirements.md).
- Public IPv4, SSH username and an existing secure access method.
- Separate neutral VPN hostname and HTTPS administrative hostname.
- Operator-managed DNS and a certificate issuance/renewal contact.
- Agreed access sources for SSH/admin and a short-lived test-account expiry.

Sizing is a planning estimate, not a concurrent-user promise. Allow approximately
7–14 days for manual client/network tests and sustained observation; retain evidence
and private backups before deleting the VM. Binary compilation belongs in CI.

## Preflight

Verify the actual hostname, IPv4, OS/architecture, sudo rights, free RAM/disk,
listeners and existing services before any installation. Record their identities
and configuration. Abort automatic fresh-node setup if SolarTT data already exists
or the intended listeners are occupied; reconcile explicitly instead.

Choose an exact tested source commit and development artifact. Verify its ZIP and
package hashes and upstream/patch provenance. Do not deploy a moving branch or
assume that a development artifact has release signatures.

The current verified source and artifact digests are in
[the pilot review](pilot-review-2026-10-06.md). CI artifacts have seven-day retention;
check availability before scheduling installation. If they have expired, rebuild
the same reviewed source and verify the new artifact's hashes and checks rather
than substituting an untested package. No persistent VM has been provisioned or
deployed as part of the automated pilot.

## Proposed routes

```text
IPv4 TCP443 → HAProxy TLS passthrough, normal idle 24h / FIN30s
  VPN hostname → 127.0.0.1:9443 managed TrustTunnel TLS/H2 (no PROXY header)
    ordinary HTTPS requests → 127.0.0.1:9080 cover origin
  admin hostname → reviewed HTTPS reverse proxy
    → 127.0.0.1:8081 panel, canonical HTTPS public_origin

TCP80 → owned HTTP-01 challenge/webroot route and HTTPS redirects
agent metrics 127.0.0.1:1987; control is a restricted Unix socket
SSH TCP22; public UDP443 is not required by this H2 scope
```

Review the reverse proxy build, PROXY listener allowlist and certificate ownership
before applying this plan. [The integration guide](proxy-integration.md) describes
the tested boundaries; test-fixture Caddy is not a production-build endorsement.
Restrict administrative access separately. Internal ports and metrics remain private.

Use separate A records for the selected test names; do not transfer an existing
zone/apex/hostname to the pilot. Plan DNS propagation from actual TTL and perform
bounded checks rather than repeated polling. Add IPv6 only under a separately
verified IPv6 scope; the initial managed release exports IPv6 disabled.

## Installation and acceptance

1. Install the checked package; verify that it does not start services by itself.
2. Review service account UIDs and Unix peer allowlist. Supply host configuration,
   master key, administrator hash and certificate/key with the documented permissions.
3. Validate merged proxy configuration and start services explicitly. Empty users
   must deny VPN authentication. Preserve a configuration/DB/key checkpoint.
4. Create expiring synthetic pilot users with explicit quotas. Verify CA/SNI,
   TCP HTTPS and UDP/DNS on the official client. Do not relax TLS verification.
5. Android: record the actual version/build; test Wi-Fi and a named mobile carrier,
   reconnect after network change, DNS behavior, expiry/quota, and revoke A while
   B's established traffic continues. Record network-specific limits, not a claim
   about all providers or a censorship cause.
6. Keep at least 24–72 hours of sustained session/cleanup observation when feasible.
   Record CPU/RSS, connection counts, WAL/DB/log growth and idle/half-close behavior.
   Do not equate runner loopback measurements with VM capacity.
7. Validate operational ACME renewal using the reviewed challenge route and managed
   reload operation. Verify a fresh certificate and preserved existing traffic.
   Fixture SIGHUP tests do not establish production renewal success.
8. Validate backup/key recovery and the exact upgrade/rollback candidate. The old
   binary must refuse schema 2, and stale-snapshot rollback must not erase new spend.

## Stop/rollback/deletion

Keep services stopped while preparing a rollback. Preserve the current database,
configuration, data key and certificate state. Use a compatible verified snapshot
and [the guarded rollback operation](isolated-pilot.md), then inspect the target
binary's schema support. It creates a new database rather than overwriting current
state. Changed policy or quota requires reconciliation before access is reopened.

On completion, revoke pilot profiles, stop services, retain sanitized results and
private encrypted/off-host backups with verified keys, then delete the temporary
VM under the operator's provider procedure. The repository contains no provider
account credentials and performs no paid VM creation or destruction.
