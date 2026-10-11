# Isolated Ubuntu process pilot — 2026-10-11

## Source and scope

The pilot used checksum-verified alpha.2 Cloud candidate ELF, built from the
review tree `2a61a9c18f518485eb28aa6b208ee8580694cca5` on base
`bae2135babed5fd05b8a125655058431209d3c06`. Original Cloud review commit
`9b6e024763b0d05998887da202a6630dd547b7f4` was local; applying its format-patches
reproduced that tree. Rust/Cargo.lock/upstream pins and managed patch were unchanged.

New target: an existing Ubuntu 24.04.5 x86_64 node with 1 vCPU and approximately
2 GiB RAM. Candidate agent/panel/admin ran as separate processes under one
unprivileged OS UID, with private runtime data and synthetic credentials.
Production VPN/proxy/SSH services retained their PIDs and configuration.
No package was installed, no public listener or route was added, and no DNS was
changed. This is process evidence, not installed-package acceptance.

| Candidate | ELF SHA256 |
| --- | --- |
| agent | `4db5ee9be4605aaf648cd778173c31cb4861461f42a3d0d9aec048c41d6dd0b8` |
| panel | `2f162755807c15e1bf6b33e3b4e8ad281c6997baa9d7fb8a3a41449649db9bca` |
| admin | `2d1de036f34e31e224ad058da1bb879375b37f9ca9b2ae8dda709f3543ff4d20` |

## New results

The complete process scenario passed **17 checkpoints**, followed by targeted
shared-ledger and restored-payload checks. These are scenarios, not a new count
of unit tests. The previous 44 Cloud tests and 139 historical CI tests remain
separate results.

| Result | Verified behavior |
| --- | --- |
| PASS | HTML/login/API, readiness/schema 2, CSRF rejection, Unix socket 0660 inside directory 0700 |
| PASS | Empty users and zero quota deny authentication; profile export/QR and trusted-UID audit |
| PASS | Verified TLS/SNI/ALPN H2; mixed principals rejected |
| PASS | Separate pinned official CLI 1.1.7 A/B forward public TLS WebSocket echo payload |
| PASS | Block/rotation/revoke A; B's established payload connection survives without reconnect |
| PASS | Expiry and certificate SIGHUP reload preserve B; private target denied; HTTP cover |
| PASS | Private HAProxy both FIN directions, no-FIN control, idle/live H2; Caddy PROXY v2 boundary |
| PASS | Sandboxed Chromium login/dashboard/profile/QR, secret clearing and logout |
| PASS | Official CLI IPv4 HTTPS and real UDP/DNS |
| PASS | Real TCP/UDP add to one user ledger; lowering limit below spend closes A and preserves B payload |
| PASS | Live SQLite backup, stopped validation, restore/check, restored agent/panel authentication |
| PASS | Restored agent forwards new public payload directly and through private HAProxy; unchanged policy and preserved/increased quota |

In the full scenario B completed 39 echo exchanges (2554 bidirectional application
payload bytes) while other operations proceeded, without reconnect. That count
excludes transport/TLS overhead and is not a throughput benchmark. In the targeted
ledger test A's confirmed count rose from 5912 bytes after TCP to 6002 after UDP.

The live snapshot conservatively retained outstanding charge: B's snapshot held
262144 charged bytes and 5748 confirmed bytes. Restore preserved that state rather
than refunding unknown spend. Subsequent public traffic increased confirmation;
the canonical policy digest remained unchanged. This illustrates the documented
live-snapshot uncertainty contract, not a quota reset.

## Memory and containment

| Process | RSS near low load | Sampled peak |
| --- | --- | --- |
| panel | 4476 KiB (4.37 MiB) | 24348 KiB (23.78 MiB) |
| agent | 11864 KiB (11.59 MiB) | 15768 KiB (15.40 MiB) |

Samples were taken every 50 ms: 568 panel / 569 agent. They exclude the proxies,
CLI, browser and supervisor, and can miss short peaks. No minimum VM size or
concurrent-user capacity is established.

The finite fixtures had a transient cgroup ceiling of 768 MiB, pressure threshold
512 MiB, CPU quota 50% of one CPU and 256 tasks. Private Python/browser dependencies
were staged locally; browser library packages were downloaded/extracted, not
installed into the host. Chromium ran with its sandbox enabled. A temporary
AppArmor rule granted userns to its exact fixture executable and was unloaded
afterward; the global userns restriction remained enabled.

## Harness issues resolved

- The initial curl SOCKS test failed without explicit IPv4 selection. `--ipv4`
  verified the currently supported IPv4 scope; IPv6 acceptance is not claimed.
- A long private directory exceeded HAProxy's 97-byte stats-socket path limit.
  Shortening only the fixture path resolved configuration validation.
- The first restored CLI connection through the fixture returned SOCKS connection
  refused. A bounded readiness/probe loop subsequently verified new payload
  directly and through HAProxy. The proxy proof recorded one startup probe error;
  it did not change policy, quota or TLS checks. A listening SOCKS socket alone
  does not prove that the upstream transport is ready.

## Observation and remaining gates

A fresh synthetic-only pilot was started on private loopback HTTP 18081, TLS/H2
19443, metrics 11987 and cover 19080. Its transient supervisor samples readiness,
RSS, FDs, DB/WAL/log growth every minute, stops on child/readiness/storage failure
or a 20-MiB log budget, and schedules 24 hours of observation. The runtime has
an outer 25-hour stop limit. It uses no production credentials. Administrative
access requires SSH forwarding with canonical origin `http://127.0.0.1:18081`;
access details stay in a private mode-0600 file.

At startup the supervisor cgroup used about 16.2 MiB and had a 35.3-MiB peak,
including initialization and cover. Cgroup attribution differs from summed RSS;
this is not the full browser fixture peak or sustained capacity.

**24-hour observation: STARTED, not yet PASS.** Android/manual client, operational
ACME, installed service-UID separation and full package lifecycle remain separate
gates. The packaging permission fix now also has a Ubuntu CI regression: current
native packages are built with umask 077 before normal payload/ELF checks and
the installed smoke/upgrade jobs. A new CI result must be recorded independently.

## Ubuntu CI follow-up: PASS

Source/workflow commit `72ec312bfb014637e0b65912f251870506d87cd2` passed all five
jobs in [run38154977805](https://github.com/precox/SolarTT-UI/actions/runs/38154977805),
completed `2026-10-11T16:29:06Z`. New functional counts:38 portable,95 patched
upstream,5 transport and1 raw-H2 = **139**. The separate release measurement and
Python/browser/lifecycle assertions are not included in that count.

| Job | ID | Result |
| --- | --- | --- |
| portable | 114515981267 | PASS: formatting, Clippy, syntax,38 tests |
| security | 114515981479 | PASS: history/source0 findings; RustSec0 known vulnerabilities |
| legacy | 114515981491 | PASS:95 tests |
| native | 114515981530 | PASS:6 functional tests, private-umask packaging, ELF/payload, installed smoke/browser, package secret scans |
| pilot | 114517580709 | PASS: actual alpha.1/alpha.2 upgrade, compatible rollback, new-spend rollback refusal, schema2 recovery, retained data/unrelated service |

Production audit used RustSec database
`7eebec69c352c7191b1f13eb95dd510eeca5d1de`; unmaintained rustls-pemfile1.0.4/2.2.0
warnings remain. Both native and pilot package/artifact scans reported0 findings.
The native log explicitly records `umask077`, successful payload/ABI validation,
installed package/browser acceptance and reinstall/removal checks.

| Artifact | ID | Bytes | GitHub ZIP SHA256 |
| --- | --- | --- | --- |
| solartt-linux-x86_64-development | 11708292629 | 16560578 | `048cde1ba8ae79fde057d93476d33e8c11a26abeb6ba3e4108566b2a99bd3773` |
| solartt-isolated-upgrade-pilot | 11707808981 | 16570099 | `f6177ca00abb798744302f83ea5ac0befb3739ad8d5b260ced3dba90a0bf5060` |

Digests agree between API metadata and upload/download logs. Retention7days;
package-level hashes are in the artifact's SHA256SUMS, not these ZIP digests.
Artifacts were not downloaded or installed over the existing production node.
The earlier separate Cloud candidate ELF remains the private live-pilot binary.

The Cloud packaging fix has now passed supported Ubuntu package acceptance.
Installed service account isolation is verified on that runner, while the RIGA
process pilot deliberately remains under one UID. Neither result proves manual
Android/ACME,24h observation or sustained node capacity.
