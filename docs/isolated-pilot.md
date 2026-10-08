# Isolated installation, upgrade and recovery pilot

The automated pilot is a separate `ubuntu-24.04` job after the tested current
packages are uploaded. It starts on a new GitHub-hosted VM without SolarTT data.
It does not run on the production workspace, create a paid VM, edit public DNS,
or provide a persistent endpoint for Android.

The runner has SDK/build tools and therefore is not a minimal Ubuntu image.
Current package ELF/linkage is checked independently. GitHub describes standard
Linux runners as fresh virtual machines:
[runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

The first complete passing run and artifact digests are recorded in
[the pilot review](pilot-review-2026-10-06.md). Deployment inputs and the remaining
client/operational checks are in [the manual pilot plan](manual-pilot-plan.md).

## Original baseline

`upstream/pilot-baseline-pin.json` fixes actual alpha.1 source commit
`7ec4b1779e20bb3268e704c82a397742e34d81ae` and its archive SHA256. The pilot
reconstructs and builds that source with its original lockfile and notices;
it does not manufacture schema 1 from new code. Current packages come from the
native job in the same workflow, with checked package hashes.

## Scenario

1. Fresh alpha.1 package install; confirm services do not auto-start. Configure
   synthetic accounts, protected key/hash files and a trusted fixture certificate.
2. Verify real H2 authentication, official CLI HTTPS and UDP/DNS payload. Stop
   cleanly, verify durable charge/confirmed counters and snapshot schema 1.
3. Upgrade to alpha.2 with unchanged account UIDs, data key, administrator hash and
   configuration. Check the old snapshot without changing it. Start and verify
   actual migration, preserved profiles, policy revision and quota charge.
4. Reject rollback while the database is active. With the agent stopped and no
   new policy/payload since the snapshot, create a compatible rollback candidate.
   Preserve the upgraded database, install old binaries and start on schema 1.
   The old binary must refuse the preserved schema-2 database.
5. Upgrade again, send new payload and reject an old-snapshot rollback that would
   erase that additional charge.
6. Snapshot schema 2; reject wrong keys, corruption and existing destinations.
   Restore to a new path, start with the same credentials/counters and forward
   additional real TCP/UDP payload.
7. Remove the package, confirm retained data/key/hash files and preserved unrelated
   sentinel and SSH service state.

`dist/pilot-report.json` contains outcomes and synthetic payload counts, not
credentials or database snapshots. All key/profile files remain private and
outside uploaded artifacts. Package/artifact secret scans run before publication.

## Safe rollback utility

The host utility provides an additional guard; the panel cannot invoke it:

```sh
sudo -u solartt-agent solartt-admin rollback OLD_SNAPSHOT CURRENT_DB KEY TIMEZONE NEW_DB
```

It requires an exclusive lock on the stopped current database, validates both
inputs and key, and compares canonical policy plus every nonzero quota ledger.
New spend, changed policy or a mismatched key refuses the candidate. A zero-charge
ledger introduced only by migration is not treated as spent traffic. Audit and
operation-receipt history can differ: preserve the upgraded database for review.

The utility creates a new destination using the snapshot's original schema and
never modifies or downgrades the existing database. Inspect that schema against
the target binary, keep the services stopped and explicitly switch binaries and
configuration. This is not an atomic host deployment or a substitute for an
operator-owned rollback plan. A standalone retention TOML is an optional final
argument for custom storage limits.

After new spend/policy changes, use a compatible current snapshot or explicitly
reconcile changes before restoring access. Ordinary `restore` can restore an old
snapshot and cannot invent missing history. Do not silently reset user allowance
by applying it as a downgrade shortcut.

## Persistent manual pilot

For a short-lived Android/real-network pilot, propose a separate Ubuntu 24.04
x86_64 VM: 2 vCPU, 2 GiB RAM, 20–30 GiB SSD and public IPv4 on a lightly loaded
node. The initial 4-GiB proposal adds headroom for shared workloads. A 1-vCPU
candidate can exercise basic behavior; these are planning estimates, not measured
minimums or user-capacity guarantees. See [runtime requirements](system-requirements.md).
Build binaries in CI. Budget about 7–14 days for operator/client
availability, sustained sessions and observation; retain results before deletion.

Use a dedicated hostname and trusted certificate, private internal listeners and
an explicitly reviewed SSH/proxy/ACME configuration. DNS, VM creation and actual
deployment are separate operator actions. Start with TCP22/80/443; current H2
mode does not require public UDP443. Android, mobile/Wi-Fi transitions, operational
ACME renewal, long-duration pressure and full host-image recovery remain manual
requirements; this workflow does not claim those outcomes.
