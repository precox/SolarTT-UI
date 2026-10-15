# Dependency notices and provenance

Development packages contain `third-party/manifest.json` and the license,
notice, copyright and author files found in the exact resolved Cargo sources,
including files inside vendored native sources. The inventory includes build,
test and target-specific dependencies; it is broader than the Linux runtime.

The collector currently accounts for 297 non-SolarTT packages from Cargo.lock.
It fails if a package lacks declared license metadata or preserved notices.
This completeness check does not replace review of license obligations before
publishing a stable release.

Some crates.io archives omit their repository license files. Supplemental files
in `upstream/notices/` preserve those originals, with the repository commit,
source URL and SHA-256 in the adjacent manifest. Where the crate contains
`.cargo_vcs_info.json`, the collector requires the same commit. The winapi
import-library archives lack that metadata; their notices come from the matching
0.4.0 packages in the upstream 0.3.9 source tree. The r-efi archive includes its
license grants and copyrights in AUTHORS; that file is preserved directly.

The root SolarTT-UI Apache-2.0 license does not relicense dependencies. Their
original expressions and attribution files remain in the package. The collector
records the declared alternatives without choosing a license on behalf of the
maintainer. No binary from the official CLI compatibility fixture is included
in SolarTT packages. The official Caddy fixture is also test-only and is not
redistributed.

Reproduce collection after downloading resolved sources:

```sh
cargo metadata --locked --format-version 1 | python3 scripts/licenses.py
```

Changing Cargo.lock may require updating supplemental notices, source commits
and the review record. Do not copy notices from an unrelated release to satisfy
the packaging gate.


## Inventory reconciliation — 2026-10-15

The exact `86827cd` artifact inventory was reconciled against the production
Cargo.lock: all 297 non-SolarTT package name/version pairs matched, with no
missing or duplicate records. Its 548 nonempty notice files (2,870,776 bytes)
were present, and each installed notice matched the artifact byte for byte.
Supplemental-source checksums also matched. Manifest SHA-256:
`971349f4850817293c869daf47610e6d447aad192cbd1a1a86c473d97731fc37`.
The [machine-readable review](dependency-inventory-2026-10-15.json) records counts,
raw license expressions and selected native/crypto notice coverage.

This review covers inventory, file presence and provenance. It does not choose
between license alternatives, convert legacy slash-separated metadata into SPDX,
or sign off on every native subcomponent's redistribution obligations. In
particular, inspect the preserved nested notices for AWS-LC, BoringSSL, ring,
quiche and bundled SQLite rather than relying only on the outer crate's license
field. The full release obligation review therefore remains open; the inventory
check is not a reason to mark the complete license gate passed.
