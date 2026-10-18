# TrustTunnel dependency

Pinned upstream: TrustTunnel/TrustTunnel v1.1.0, commit
`fab5b8353a19332f935fa30869307d37d4a898d1`. Apache-2.0.

`pin.json` records the exact release tag for version tracking. The watcher checks
that tag against the commit; builds still download by commit and verify SHA256.

`python3 scripts/prepare_upstream.py` retrieves a SHA256-checked archive and
applies reviewed patches from this directory to `.upstream/`. This generated
directory is excluded from Git. All changes to upstream are recorded in patch
files; production builds do not follow a moving branch. The patch set can move
to a dedicated upstream fork later without changing the control API.

Upstream owns TLS, HTTP/2 and forwarding. SolarTT owns identities, policy, quota
periods, persistence and administration. No protocol extensions or custom clients
are intended. Compatibility must be established by tests before releases.

See [upstream maintenance](../docs/upstream-maintenance.md) for the weekly stable
release watcher, issue deduplication and the separate reviewed update process.
Discovery never replaces the managed agent or changes this pin automatically.
