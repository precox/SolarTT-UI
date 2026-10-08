# Runtime requirements and pilot sizing

## Supported runtime

The development package targets **Ubuntu 24.04, Linux x86_64, systemd**.
Other distributions/architectures have not passed package acceptance. Install
tested CI binaries on the node; Rust, CMake, libclang, Node and Chromium are not
runtime dependencies of the packaged panel/agent. Browser acceptance runs in CI;
administrators use their own browser to open the web interface.

The runtime contains separate `solartt-panel`, `solartt-agent` and host-only
`solartt-admin` binaries. A reviewed TLS passthrough proxy and administrative
HTTPS reverse proxy add their own resource use. The panel does not forward VPN
payload; the TrustTunnel agent does.

## Small pilot: planning estimates

| Resource | Planning target for one or two test clients |
| --- | --- |
| CPU | 1 vCPU candidate; 2 vCPU preferred for the pilot |
| RAM | 2 GiB total on a lightly loaded node |
| VM disk | 20–30 GiB for OS, packages, logs and backups |
| Connectivity | Reachable IPv4, reviewed TCP443 entry and administrative access |
| Build | In CI, with native build tools; not on the pilot node |

These are planning estimates, **not measured minimum requirements or a
concurrent-user capacity**. The earlier 2 vCPU / 4 GiB / 30 GiB proposal provides
extra headroom for a shared test node; 4 GiB is not a panel requirement. The VM
disk target is also not the installed package size. Measure actual services,
logs and backups before publishing a minimum disk requirement.

On 2026-10-08 the existing 2-vCPU / 1967-MiB UK node had 1510 MiB available with
its unrelated browser service stopped. That snapshot supports attempting a
small monitored pilot; it does not validate sustained capacity or concurrent
browser workloads. The unrelated browser remains managed on demand and its
future peak must be accounted for separately.

## Configured memory ceilings

| Service | MemoryHigh | MemoryMax |
| --- | --- | --- |
| Panel | 128 MiB | 192 MiB |
| TrustTunnel agent | 384 MiB | 512 MiB |

These values are resource containment defaults. `MemoryHigh` applies pressure;
`MemoryMax` caps consumption. They do not preallocate that amount of RAM and do
not describe normal RSS. See [Ubuntu's cgroup documentation](https://documentation.ubuntu.com/security/security-features/privilege-restriction/cgroups/).

The combined 704-MiB ceiling excludes the OS, proxy services and unrelated
applications. It is useful for budgeting peaks, not as a measured minimum.
Reaching a cap can terminate/restart a service and interrupt sessions. Tune
limits only from observed workloads; do not remove containment to meet a
smaller advertised footprint.

## What has actually been measured

The recorded release transport fixture used about 17–18 MiB RSS in its single
test process, including the client and echo servers. It excluded the installed
panel, host proxies and full-node overhead. It therefore cannot establish the
panel's memory use or the complete deployment footprint. See
[the verification record](verification.md).

Standalone installed panel RSS, the installed agent/proxy footprint under
representative concurrent traffic, long-lived sessions, and CPU/disk costs on
the intended node remain to be recorded during the authorized pilot. Before
publishing stable minimum requirements or a users-per-node estimate, measure
idle, normal operation and bounded peak behavior, including concurrent
administrative login/export and unrelated scheduled workloads.
