# Architecture and access semantics

The agent hosts a pinned TrustTunnel core with an opt-in policy adapter. The
panel is a separate unprivileged process; only the agent owns canonical policy
and traffic state. Panel downtime must not disable the VPN or suspend expiry.

## Identity

A stable UserId owns one or more CredentialIds. Each TLS/H2 transport binds to
one credential and its generation. Mixed credentials on one transport are
rejected. Client IP addresses are not user identities.

Blocking, expiry and final quota exhaustion reject new authenticated requests,
terminate the user's TCP/UDP exchanges and close that user's TLS transports.
Revoking a credential targets its sessions only. A successful applied revision
acknowledges resource cleanup; a timeout must be reported as pending/error.
This does not promise a specific Android VPN indicator: clients may reconnect.
Bytes already enqueued in the network cannot be recalled. Process crashes,
upgrades and host reboot can still interrupt every user.

## Quota

Sum forwarded TCP/UDP payload, both directions, across all profiles of one user.
Reserve before writing; refund unsent TCP bytes and explicitly dropped UDP. Permits cancelled before a
write starts are refunded; a cancelled write with unknown delivery stays charged. A UDP datagram is admitted whole or rejected. Concurrent reservations
are distinct from confirmed consumption. No periodic metrics-only enforcement.

Persisted byte leases prevent restart-based quota resets. Unknown unused leases
after a crash can be conservatively charged; delivered and reserved amounts are
shown separately. This is access enforcement, not exact delivery billing.

## Dependencies

The pinned upstream and patch checksums are part of each release. All builds
are marked as derivatives. The initial patch interfaces must preserve legacy
behavior when managed mode is absent. Monthly policy, database and panel logic
remain outside the upstream core.

## Calendar and durability

A database has one immutable IANA timezone. Users can enable calendar-month
resets or use manual periods. Missed months are skipped to the current month,
without accumulating allowances. Periods retain archived consumption; reusing
an old period retains its old charge. Transitions pause new byte permits until
outstanding writes finalize. Already cancelled TLS sessions are not revived by
a reset; clients establish fresh transports.

The shared pool is at most 256 KiB per user. A crash can lose proof of unused
bytes within that pool. Unknown cancelled writes remain charged additionally;
confirmed counters describe known accepted payload rather than delivery receipts.
Clean shutdown refunds only proven unused credit. Idempotency keys, audit,
calendar metadata and credential generations are committed in SQLite.

Initial resource caps: 256 users, 16 credentials per user, 32 authenticated
transports per user, 128 concurrent inbound TLS connections globally in managed
mode. The core has a separate bounded request registry. These are protective
caps, not measured capacity or throughput guarantees. The legacy static-client
connection limiter is bypassed in managed mode; the policy engine owns dynamic
user limits. Legacy mode retains its existing limiter behavior.

Managed forwarding also caps 256 flows per UDP multiplexer and 1024 TCP plus
1024 UDP outbound sockets globally. TCP socket permits survive until both halves
are dropped; UDP permits are released with their socket. Existing UDP flows keep
working when new-flow admission is full. These global caps do not promise fair
allocation between users. Packaged systemd units additionally contain memory,
tasks and file descriptors; tune their limits using measured workloads.

## Control boundary

Control API v1 uses one bounded JSON frame per Unix connection, peer UID checks,
idempotent policy mutations and expected revisions. User and audit lists are
paginated. TLS reload is a host administrator SIGHUP operation, outside policy
revisions, and reads only the configured certificate paths. The panel exposes
no shell, file upload, database restore or infrastructure configuration API.
