## Change and release identity

Closes #<!-- upstream discovery issue -->

Describe the user-visible and operator-visible change and why this release was selected.

| Item | Current supported release | Proposed release |
| --- | --- | --- |
| SolarTT version / source commit | | |
| TrustTunnel tag / source commit | | |
| Upstream archive SHA256 | | |

Link the upstream release notes and source comparison. Record how the proposed
commit and archive checksum were independently verified.

## Managed patch and compatibility

Describe each affected managed hook, any upstream replacement for an existing
fix, and the reason for dropping or rewriting a patch hunk. Successful patch
application alone does not establish compatibility.

| Boundary | Change and compatibility evidence, or explicit reason it is unaffected |
| --- | --- |
| Panel / agent API and capabilities | |
| Database schema, policy and durable quota accounting | |
| Configuration and defaults | |
| Profile export and supported official clients | |
| TLS, HTTP/2, forwarding and revocation isolation | |
| Dependencies, lockfiles, licenses and exact notices | |

## Automated evidence

Link the exact candidate commit's CI run and relevant reports. Leave unverified
items unchecked and explain missing coverage.

- [ ] All six release gates pass: security, portable, native, legacy, pilot and minimal.
- [ ] H2 durable-lease regression reproduces the pre-fix failure and passes after the fix.
- [ ] Quota admission/exhaustion and revoke A while B's TCP/UDP streams survive pass.
- [ ] Fresh installation, supported upgrade paths and restore checks pass on disposable runners.
- [ ] Supported previous SolarTT versions tested are listed explicitly; historical alpha.1 migration alone is not evidence for an upgrade from alpha.5.
- [ ] Both pilot matrix reports pass; alpha.5 baseline/candidate source and package hashes match this PR's candidate.
- [ ] Required dependency notices and redistribution review are current.

## Human acceptance

Record what needs the owner's decision, who tested it, the test build/client
versions, environment and results. Use an isolated test environment and temporary
profiles; keep credentials and private logs out of this PR.

- [ ] User-visible behavior and known limitations reviewed.
- [ ] Applicable panel/profile/client checks completed, or explicitly deferred with a reason.
- [ ] For agent/panel behavior changes, the exact candidate's manual acceptance kit and completed owner record are linked; kit preparation alone is not marked as acceptance.

## Release, rollout and recovery

List incompatible changes, backup/key requirements, supported recovery or
downgrade paths and the validation performed. Explain when rollback requires
restoring data and how quota/policy changes since a snapshot are handled.

PR approval, package publication and Riga installation are separate decisions.
Record publication authorization separately. Installation requires its own agreed
window, backup and recovery plan in the operational workflow; merging this PR
does not authorize server access, installation or a VPN restart.
