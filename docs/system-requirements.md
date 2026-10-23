# Runtime requirements and pilot sizing

## Supported runtime

The v0.1.0 package targets **Ubuntu 24.04, Linux x86_64, systemd**.
Other distributions/architectures have not passed package acceptance. Install
tested CI binaries on the node; Rust, CMake, libclang, Node and Chromium are not
runtime dependencies of the packaged panel/agent. Browser acceptance runs in CI;
administrators use their own browser to open the web interface.

The runtime contains separate `solartt-panel`, `solartt-agent` and host-only
`solartt-admin` binaries. A reviewed TLS passthrough proxy and optional administrative
HTTPS reverse proxy add their own resource use. The panel does not forward VPN
payload; the TrustTunnel agent does.

## Small pilot: planning estimates

| Resource | Planning target for one or two test clients |
| --- | --- |
| CPU | 1 vCPU candidate; 2 vCPU preferred for the pilot |
| RAM | 2 GiB total on a lightly loaded node |
| VM disk | 20–30 GiB for OS, packages, logs and backups |
| Connectivity | Reachable IPv4, reviewed TCP/TLS entry and administrative access |
| Build | In CI, with native build tools; not on the pilot node |

These are planning estimates, **not measured minimum requirements or a
concurrent-user capacity**. The earlier 2 vCPU / 4 GiB / 30 GiB proposal provides
extra headroom for a shared test node; 4 GiB is not a panel requirement. The VM
disk target is also not the installed package size. Measure actual services,
logs and backups before publishing a minimum disk requirement.

The 2-GiB figure budgets the whole VM, including OS, existing services and
headroom. It is not an allocation requested by SolarTT. A shared 1-vCPU/2-GiB
Ubuntu node has run the small operator pilot; this establishes feasibility for
that workload, not a measured minimum or a capacity promise. No native builds
should run on such a shared node.

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

The [2026-10-11 process pilot](process-pilot-review-2026-10-11.md) measured separate
candidate processes on an existing 1-vCPU / 2-GiB Ubuntu node: panel approximately
4.37 MiB low-load RSS / 23.78 MiB sampled peak; agent 11.59 / 15.40 MiB. These
exclude browser/proxies/client and are not installed-stack or sustained-capacity
measurements. The separate prior Cloud report measured panel 3.1 / 22.4 MiB and
agent 10.3 / 14.8 MiB; those were different runs. Configured ceilings remain
192 MiB panel and 512 MiB agent.

The recorded release transport fixture used about 17–18 MiB RSS in its single
test process, including the client and echo servers. It excluded the installed
panel, host proxies and full-node overhead. It therefore cannot establish the
panel's memory use or the complete deployment footprint. See
[the verification record](verification.md).

A 2026-10-17 installed-node low-load point sample was about 4 MiB panel RSS and
9 MiB agent RSS. It excludes host proxies and does not represent a simultaneous
loaded peak. The package's runtime ELF libraries are checked independently in CI;
actual installed disk size is included in the minimal-runtime release report.
The 2026-10-22–23 installed alpha.6 observation lasted 24 hours: agent RSS
peaked at 17.36 MiB and panel at 4.45 MiB across 1,373 samples, with no OOMs
or service restarts. This included idle periods and is not a capacity benchmark.
[The acceptance record](stable-acceptance-2026-10-23.md) describes its scope.
Representative concurrent traffic, throughput, UDP loss and disk costs still
need measurement. Before
publishing stable minimum requirements or a users-per-node estimate, measure
idle, normal operation and bounded peak behavior, including concurrent
administrative login/export and unrelated scheduled workloads.

## Optional swap and pilot duration

A 1-GiB SSD-backed swap file is a proposed reserve for transient memory pressure,
not a prerequisite for starting this small pilot. Swapping eligible cold pages
can help reclaim RAM; active swapping adds I/O latency, and cgroup memory/swap
limits still apply. Do not count swap as fast RAM or as proof that a service
cannot run out of memory. See [kernel memory concepts](https://docs.kernel.org/admin-guide/mm/concepts.html)
and [cgroup memory/swap limits](https://docs.kernel.org/admin-guide/cgroup-v2.html).
A 1-GiB swap file exists on the operator pilot node; the package does not create
or tune swap on an installing machine.

Basic pilot planning: about one working day for installation and functional
client/recovery checks, followed by 24–72 hours of observation. That is roughly
2–4 calendar days if DNS, certificates and client access are ready and no blocker
appears. The original 7–14-day window is optional calendar headroom for operator
availability, additional networks or longer observation; it is not mandatory
test execution time. The v0.1.0 acceptance decision and deferred measurements remain separate.
