# Isolated upgrade and recovery review — 2026-10-06

## Verified source and CI

Source: `47b24b713a50f08e020e3a8143d2c69a493f56e8`, development branch
`dev/v0.1`, version `0.1.0-alpha.2`. This is a development build, not a stable
release or production deployment. No production service, DNS or firewall was
changed by this stage.

[Actions run 37516135465](https://github.com/precox/SolarTT-UI/actions/runs/37516135465)
completed successfully on 2026-10-06 at 19:16:25 UTC. All five jobs passed:

| Job | Job ID | Result |
| --- | --- | --- |
| portable | 112449387477 | Formatting, Clippy, JavaScript syntax; 38 tests |
| legacy | 112449387740 | 95 patched upstream tests |
| native | 112449387763 | 5 transport and 1 raw-H2 tests; measurement, package and browser acceptance |
| security | 112449387799 | Full history/source secret scans and production RustSec audit |
| pilot | 112453860702 | Actual version upgrade, compatible rollback, recovery and removal on a fresh VM |

The 139 functional tests exclude the separately invoked release measurement and
the Python/browser package acceptance assertions. Existing native tests for
HAProxy FIN cleanup, Caddy PROXY v2, TLS reload, profile clearing and ELF/runtime
linkage passed again. The new pilot does not replace those checks.

## Actual baseline and outcomes

The pilot builds original alpha.1 source
`7ec4b1779e20bb3268e704c82a397742e34d81ae` with its original lockfile and dependency
notices. Its codeload archive SHA256 is
`09aa6cc8aa640fccba0c1e3a5ad85fb0010c7daf7eaa995af47e1c444a129b48`.
The pin is committed in `upstream/pilot-baseline-pin.json`. Current alpha.2
packages are downloaded from the native job in the same workflow; their artifact
digest and package checksums are verified before installation.

The completed pilot job logged all six successful checkpoints:

1. Fresh alpha.1 install without service autostart, trusted fixture TLS,
   official CLI 1.1.7 TCP HTTPS and real UDP/DNS payload. Clean shutdown persisted
   positive charge/confirmed counters and a schema-1 snapshot.
2. Actual alpha.1 → alpha.2 upgrade and migration, preserving service account
   UIDs, key, administrator hash, configuration, credential, policy revision and
   quota counters. Read-only validation left the old snapshot unchanged.
3. Rollback refused while the database was active. Once stopped, the guarded
   operation created a compatible schema-1 candidate without changing the
   retained schema-2 database. Actual old binaries refused schema 2 and started
   successfully on the candidate with the original profile.
4. Following another upgrade and additional live payload, rollback from the old
   snapshot was refused because it would erase new quota charges.
5. Schema-2 restore rejected wrong keys, corruption and an existing destination.
   Valid restore to a new path preserved identity and counters; the restored
   service then forwarded additional real TCP and UDP payload.
6. Package removal retained database/key/hash data. A separately started sentinel
   service kept its nonzero PID throughout the lifecycle; existing SSH service
   state also remained unchanged.

`dist/pilot-report.json` in the pilot artifact contains the checkpoint results,
baseline/version/schema identifiers and synthetic payload counters. This review
uses completed job logs and artifact API metadata; the artifact report was not
downloaded into the production workspace. No fixture profiles, private keys,
master keys or database snapshots are uploaded by the pilot.

## Artifact identity

| Artifact | ID | Size (bytes) | SHA256 of GitHub artifact ZIP |
| --- | --- | --- | --- |
| solartt-linux-x86_64-development | 11436964459 | 16541817 | `0afd1ee19cf84ec0c7fbd27d082e846f852d0f8ee35b253bb5b57f1fc69b9ab9` |
| solartt-isolated-upgrade-pilot | 11438381121 | 16551339 | `2f2d8978250061fd02a0c7462741034eb6d4872f7191dfa5382d4ce8e1173887` |

Both were available when reviewed and have seven-day CI retention. ZIP digests
come from GitHub metadata and agree with upload/download logs. They identify the
uploaded containers; package-level hashes are in `SHA256SUMS` inside the artifact.
They are not release signatures. Do not invent or substitute a package hash from
the ZIP digest.

## Security and fixes during verification

The security job reported zero history/source secret findings and zero known
production-lockfile vulnerabilities, using RustSec database commit
`ef6173cbc5c50ec8166f9a5b28f07834144373ee`. Unmaintained warnings for
`rustls-pemfile` 1.0.4 and 2.2.0 remain visible. Both native and pilot jobs reported
zero findings in unpacked packages and artifact files. These are scanner results,
not proof that every dependency or code path is safe. The collected notices cover
297 dependencies; release license-obligation review remains open.

Two preceding runs exposed verification issues:

- Run 37514135229 stopped at an overly strict CLI version assertion: the agent
  includes its TrustTunnel provenance after the SolarTT version. Commit
  `4becb3edd233bc9b4a92a923e2fba8661f069e65` checks the version token separately.
- Run 37515269804 failed while removing Chrome's temporary profile after browser
  assertions: a terminating renderer could recreate a directory. Commit
  `47b24b713a50f08e020e3a8143d2c69a493f56e8` adds bounded removal retries; persistent
  cleanup errors still fail the job. The passing run exercised browser cleanup.

GitHub also logged Node deprecation notices and forced Node-24 execution for
three pinned Node-20 actions. The jobs passed; review those action pins during
CI maintenance without treating the notices as a failed runtime dependency audit.

## Scope and next gate

This VM is a fresh GitHub-hosted Ubuntu 24.04 runner with SDK/build tools, not a
minimal persistent Ubuntu node. The payload probes use runner Internet egress
and a fixture certificate. No Android connection, mobile-carrier comparison,
operational public ACME renewal, sustained capacity test or full host-image
recovery is established by this result.

Guarded rollback compares policy and nonzero quota ledgers. Audit and operation
receipt histories may differ; retain the upgraded database. The utility creates
a new candidate and does not switch binaries/configuration or make a host-wide
rollback atomic. Keep services stopped through the operator-controlled switch.

Proceed with [the persistent manual pilot plan](manual-pilot-plan.md): proposed
Ubuntu 24.04 x86_64, 2 vCPU, 4 GiB RAM, 30 GiB SSD, public IPv4 and approximately
7–14 days. Actual hostname/IPv4, SSH access and deployment approval are required
before that infrastructure step. Preserve the existing HostVDS services.
