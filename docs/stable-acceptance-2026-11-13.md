# Stable v0.1.2 acceptance

On 13 November 2026 the owner requested an additional independent review and
stable publication after successful results. This decision follows the scoped
Chrome acceptance of cancellation and permanent deletion of synthetic A with B
retained. The panel implementation is unchanged from that accepted alpha. Exact
source/package identities and the final results are recorded in
[v0.1.2-acceptance.json](releases/v0.1.2-acceptance.json) and
[v0.1.2-checks.json](releases/v0.1.2-checks.json).

## Reviewed correction

Astra reproduced a pre-existing P2 in concurrent quota refills: a queued worker
could deny an otherwise allowed stream after another worker had already filled
the shared pool. The stable candidate replans zero-grant refills and checks
counter headroom before queueing another refill. The reviewer checked the actual
source correction and deterministic TCP/UDP, finite-quota and counter-boundary
regressions. No remaining code-review blockers were identified. This review is
separate from owner acceptance and the exact-source CI and built-package checks.

The tested candidate was built from the PR's synthetic merge commit; its source
archive was compared byte-for-byte with the reviewed branch. The final tagged
package has its own source identity and SHA256. Final release preparation must
preserve the tested runtime and requires fresh exact-tag CI.

## Observation and recovery scope

The current observation uses isolated, resource-limited non-root processes,
synthetic identities and a private test CA on a shared Ubuntu host. It is a
short light-traffic run with original TCP/DoT and UDP/DNS transports. It exercises
scoped deletion, a lost first response, same-request replay, denial of old
credentials, B continuity and local snapshot recovery. Concrete duration, samples,
counts and outcome are in the checks summary; the historical v0.1.1 20h39m run is
not carried forward as observation of this modified runtime.

Earlier A timeouts remain recorded as inconclusive diagnostic failures. The old
helper could wait after an H2 stream had already ended; the corrected helper
detects that state before reading again. This does not establish the cause of either
earlier failure. Separate direct-versus-tunnel and mixed TCP/UDP comparisons
passed without reconnects. No earlier failed segment is relabelled PASS.

The local recovery scope is a matching-key synthetic database snapshot. It does
not establish complete recovery after losing a host. Package lifecycle and
upgrade tests run on disposable GitHub VMs; no production package installation
is part of this acceptance.

## Accepted verification limits

Capacity, independent full-stack recovery and actual public-certificate
replacement retain the prior documented limits. ACME staging issuance/renewal
was tested for v0.1.1 and is historical evidence for the unchanged TLS/reload
implementation; it was not repeated for v0.1.2. Network reachability, throughput,
UDP loss and a concurrent-user capacity are not guaranteed. The user's browser
was Chrome; its exact version and the user's OS were not reported. Scoped panel
acceptance does not add new physical VPN client or platform coverage.

The owner authorized stable GitHub publication subject to successful review and
checks. Exact-tag CI, dependency/security checks and public-file verification
remain mandatory. Production installation requires a separate instruction.
