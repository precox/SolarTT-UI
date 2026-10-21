# Alpha.6 scoped owner acceptance — 2026-10-21

Status: **PASS for the listed flows; temporary cohost removed**. This record
does not authorize publication, production rollout or stable support.

## Identity

| Input | Recorded value |
| --- | --- |
| Candidate | 0.1.0-alpha.6; PR #15 HEAD `0849fb96f0ff14b9d016ee2e7e257ba9b2a297e5` |
| CI build source | `014ef8f2029f7fc37b1d8a350c6f3f03b2b9d0b0` |
| Matching source tree | `f5b5576a5a82c49978cb841d201551fe846924cc` |
| Accepted deb SHA256 | `610314574cf73622af2562cf0f0768e57da56cdd557b36108be49e07260b9868` |
| CI run | [39563753115](https://github.com/precox/SolarTT-UI/actions/runs/39563753115), seven required jobs PASS |
| Environment | Owner-authorized process cohost, Ubuntu 24.04 x86_64; shared kernel/resources with an unchanged production stack |
| Window | 2026-10-21, approximately 21:29:52–21:46:33 UTC; final removal verified at 21:47:14 UTC |
| Client | Official Android app; owner previously reported TrustTunnel 1.2.0 / Android 17; exact installed build not rechecked in this session |
| Networks | Owner's SkyNet Wi-Fi and T-Mobile mobile access |
| Private evidence | Operator-held QA record: preflight, heartbeat, limit correction, revoke, teardown and checksum manifest; no profiles or raw captures published |

The agent, panel and admin ELF files in that package have these SHA256 values:

```text
20ac75153224549a8b61cd1410a44c8fb47bd59cb0c9760578824de761ba961a  solartt-agent
6f44a2bf5217fae4b4718d7a8a32b0d04331a56bef3b0eb1c56cbe2ddbcfdc4c  solartt-panel
8c70d061c6c57cea79ede8f9d4c84a14adb8c79ef6f703b575ff1b815b829f15  solartt-admin
```

Only the agent was deployed as a candidate service. Panel/admin version commands
passed; changed panel flows were not claimed. No package installation, native
build or production data import ran on the operator host. Synthetic A/B had
their own OS identity, database, encryption key and Unix socket. A separate
private test CA/leaf was supplied in A's profile; TLS verification stayed enabled.
The new profile was an audited export augmented with the official certificate
TLV for this test trust anchor. No production certificate/key was copied.

## Results

| Check | Result |
| --- | --- |
| Android profile import | PASS, owner confirmed |
| Initial Wi-Fi pages, Telegram and VPN IPv4 | PASS, owner confirmed |
| Wi-Fi → mobile with VPN active | Initial result confounded by QA maxconn=12; PASS after correction, with no manual VPN reconnect requested |
| Mobile → Wi-Fi with VPN active | PASS, automatic recovery confirmed |
| Original B TCP/UDP through listener deadline | PASS, 979.3 seconds and 323 successful pairs; same TLS transport and original TCP/UDP CONNECTs |
| New CONNECT / auxiliary health CONNECT / reconnect of B | 0 / 0 / 0 |
| Revoke A after listener deadline | PASS, A transports closed; owner confirmed failed access including after reconnect |
| Preserve B across A revocation | PASS, 50 additional TCP/UDP pairs on the original streams |
| Existing production | PID/config hashes unchanged, installed package remained alpha.5 |
| Teardown | PASS, QA credentials revoked/blocked; processes, listeners, firewall rule, timer, account, state/runtime and private keys removed |

## Test-harness incident

The temporary HAProxy frontend initially allowed 12 TCP connections. During
network switching all slots were occupied and the listen queue reached 13.
Chrome showed DNS_PROBE_STARTED, Telegram was affected and an existing ChatGPT
connection still worked. The diagnostic text alone did not identify a DNS cause.

The operator raised only the temporary frontend limit to 64 and gracefully
replaced the QA proxy using `-sf`. The candidate agent and production proxy were
not restarted. B retained its exact original TLS and stream identity throughout.
The queue cleared; the owner confirmed restored mobile access and reverse
handover. The initial incident is retained as a harness confounder, not attributed
to a candidate runtime defect. No second B segment was substituted.

## Deferred checks and release bridge

- Repeating every unchanged panel/quota/expiry/calendar path manually: DEFER;
  baseline acceptance and CI remain separate evidence. This check covers the
  changed transport, Android recovery and scoped revocation.
- Package lifecycle and alpha.1/alpha.5 upgrade: separate disposable-VM CI,
  not performed on the cohost by this manual session.
- Exact current Android build, exhaustive networks, sustained capacity, a public
  ACME trust path/replacement and off-host recovery: not established here.
- Future tagged artifacts: need their own CI and source/build identity. A
  documentation-only source change must be reviewed as such, and actual ELF
  hashes compared with the above accepted runtime. Unexpected runtime changes
  need new scoped acceptance; package digests are never silently substituted.

Owner decision: **ACCEPT for the listed functional flows**, based on explicit
step confirmations in the agreed window. Publication and production rollout
remain separately authorized operations.
