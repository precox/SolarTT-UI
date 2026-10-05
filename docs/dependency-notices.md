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
in SolarTT packages.

Reproduce collection after downloading resolved sources:

```sh
cargo metadata --locked --format-version 1 | python3 scripts/licenses.py
```

Changing Cargo.lock may require updating supplemental notices, source commits
and the review record. Do not copy notices from an unrelated release to satisfy
the packaging gate.
