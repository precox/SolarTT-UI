# Security review — 2026-10-05

Historical review of the baseline below. Alpha.2's export audit, retention and
storage follow-up is recorded [separately](storage-review-2026-10-06.md).

Scope: the public SolarTT-UI source, reachable Git history, dependency lockfile,
panel/agent boundaries, packaging and GitHub Actions. Baseline:
`fddb8086d01a468f21618c080f3567e25b487425` on `dev/v0.1`.
This is an engineering review with automated checks, not an independent penetration
test or a guarantee that every vulnerability or secret format has been found.

## Credentials and publication

- Fetched the full history and all remote branches/tags. At baseline there were
  two branches, no tags or pull refs, 10 reachable commits and 91 distinct blobs.
- Gitleaks 8.30.1 found no confirmed credentials. Its two initial findings were
  the literal Rust crate path `crates/policy` in `Cargo.toml`. The configuration
  excludes only that exact value in a Cargo manifest; other findings fail CI.
- All 23 available job logs from the eight earlier CI runs also passed Gitleaks.
  Locally generated disposable SSH keys were correctly rejected; the manifest
  exception was tested against another filename and did not suppress it.
- A separate byte comparison found no copy of the local SSH deploy private key
  in any reachable blob. The ignored local key has mode `0600`; it is not a
  project file or package input. No private-key material is included in this report.
- Source scans also cover tracked working files and decode encoded values up to
  two levels. `.gitignore` is preventive convenience, not the security boundary.
- CI now scans both unpacked `.deb`/tar packages and the artifact directory before
  uploading. Local fixtures, TLS keys, client profiles and browser state belong
  under ignored temporary directories and are excluded from package inputs.

No history rewrite or credential rotation is indicated by these scan results.
Raw random binary keys and unfamiliar formats can escape pattern-based scanners;
they must never be added to Git even if a scan passes.

## Findings and changes

| Finding | Assessment | Change |
| --- | --- | --- |
| `h2 0.3.27`, RUSTSEC-2026-0258 | Known remote denial of service from excessive empty DATA frames; upstream rates it Low. H2 passthrough does not filter these frames. | Resolved production transport and tests now use `h2 0.4.19`. A small HTTP type bridge preserves TrustTunnel's existing internal API. A raw-frame regression keeps an incoming body unread and expects `ENHANCE_YOUR_CALM`. |
| Unbounded UDP flow metadata and outbound sockets | An authenticated client could exhaust file descriptors, memory and readiness polling work. Failed UDP admission also retained a phantom metadata entry. | Managed mode allows 256 flows per UDP multiplexer and 1024 TCP plus 1024 UDP outbound sockets globally. Socket permits remain held for their complete lifetime; failed admission leaves no metadata. Tests cover caps, cleanup and continued existing traffic. |
| Unscrubbed malformed-request diagnostics | Two request error paths could include authorization/cookie headers if verbose logging is enabled. | Both paths use upstream's sensitive-header scrubber. Normal credential debug formatting was already redacted. |
| No automated secret/advisory gate | A later commit or dependency change could publish a secret or known vulnerability unnoticed. | Added checksum-pinned Gitleaks/cargo-audit checks with redacted output; vulnerabilities fail CI without advisory exceptions. |
| Checkout credentials persisted in runner configuration | Unnecessary credential access for subsequent build scripts. | Disabled persistence in every checkout; workflow token permissions remain `contents: read`. |
| Process resource containment incomplete | A transport-level cap cannot bound every allocation or public HTTP connection. | Added service-local memory, task and file descriptor limits; these bound damage to the host and do not establish load capacity. |

Primary advisory: [hyper/h2 GHSA-q83h-524g-xf6h](https://github.com/hyperium/hyper/security/advisories/GHSA-q83h-524g-xf6h),
[RustSec RUSTSEC-2026-0258](https://rustsec.org/advisories/RUSTSEC-2026-0258.html).

## Boundaries reviewed

- Panel binds loopback and requires a canonical Host and exact Origin for unsafe
  methods. Commands and secret exports require an authenticated session plus CSRF.
  Cookies use HttpOnly, SameSite=Strict and Secure for HTTPS. Argon2 login work and
  attempts are bounded. CSP, no-store and text-only label rendering protect exports.
- Agent control uses a bounded Unix-socket frame, peer UID allowlist and restricted
  filesystem permissions. UID 0 is not implicitly admitted to the control API.
  The panel account cannot read the agent master key or TLS private keys.
- Agent and panel are separate unprivileged services without Linux capabilities.
  The host administrator is trusted. No HTTP shell, file upload, arbitrary path,
  database restore, proxy or firewall management API exists.
- Credentials are encrypted with ChaCha20-Poly1305; quota grants are persisted
  before forwarding. Blocking, rotation, expiry and exhaustion cancel the intended
  sessions. Private/metadata/local destinations are rejected after resolution.
- Build dependencies, upstream archives, official test CLI and Actions are pinned
  to checksums/commits. Package contents come from explicit inputs. This does not
  constitute a full audit of vendored C/C++ TLS code or operating system packages.

## Remaining limitations

- RustSec reports `rustls-pemfile 1.0.4` and `2.2.0` as **unmaintained**, not as
  known exploitable vulnerabilities. They enter through upstream dependencies;
  migrating these parsers is still required maintenance work. No warning is hidden.
- Authenticated users can consume the shared connection budget and affect others.
  Caps contain resource use but do not provide per-user fairness or DDoS protection.
  Memory limits can restart a service during overload. Capacity/load testing remains
  a release gate. TLS passthrough alone is not an H2 application firewall.
- Audit, idempotency and historical ledgers have no retention policy yet. Profile
  export reads are not recorded in the audit table. Monitor disk space and keep
  the panel private while the project is an alpha.
- Release signing, provenance attestation, full native dependency advisories,
  cross-version migrations and independent penetration testing remain open.
- GitHub returned no repository rulesets. Legacy branch protection and private
  vulnerability-report settings could not be verified with the integration's API
  permissions. An empty ruleset list does not prove that branch protection is absent.
  No repository administration settings were changed.
- Production HostVDS services, certificates and firewall were outside this review.

## Reproduction and evidence

On Linux x86_64 with Python 3.12+ and a full clone:

```sh
python3 scripts/security_check.py source
# After building packages:
python3 scripts/security_check.py artifacts
```

Tools are downloaded from official releases and checked against committed SHA256
digests. Reports remain in ignored `.dev/security`; logs print locations and rule
names, never matched secret contents. The dependency audit fetches the current
RustSec database on each run rather than freezing vulnerability knowledge.

Local post-change source/history scans passed. The production `Cargo.lock` scan
found zero known vulnerabilities using RustSec database commit
`ef6173cbc5c50ec8166f9a5b28f07834144373ee` (1290 advisories). All 26 portable tests
passed.

All four jobs passed for code commit
`78520563ce178f64d81fc5f84424a6baf90af228` in
[Actions run 37306928493](https://github.com/precox/SolarTT-UI/actions/runs/37306928493):
26 portable tests, 95 upstream library tests, 5 managed transport tests and
1 raw-frame security regression (127 total), plus the explicit release measurement.
Installed-package, official CLI and headless browser checks passed. Both unpacked
packages and artifact files had zero Gitleaks findings. Development artifact
`11344456785` has ZIP digest
`sha256:2e3f1c427de6714213e8ba9589dc21ab68c677b67ba2958f3f67feb79e49f3b1`.
The final review/documentation commit does not change the tested application code.
