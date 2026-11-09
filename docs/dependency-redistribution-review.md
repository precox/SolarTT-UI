# Alpha redistribution review — 2026-10-17

Scope: the exact 297 non-SolarTT packages resolved by Cargo.lock, including
build/test and other-platform packages. This is an engineering review of the
release's preservation and redistribution conditions, not a legal opinion or
relicensing of upstream works. It applies to alpha releases as well as stable.

## Decisions and obligations

`upstream/license-review.json` records the original expression, selected license
and every preserved notice's SHA-256 for each package. The original expressions
and all alternative license texts remain in `third-party/manifest.json` and its
notice tree. MIT is selected for the reviewed MIT/Apache alternatives (including
legacy slash metadata); Apache-2.0 is selected for ryu's Apache/Boost choice,
CC0-1.0 for dunce (matching its supplied full license text), and MIT for r-efi rather than its LGPL alternative. Independent
AND terms are retained. Unicode-3.0 is retained in addition to unicode-ident's
MIT choice. No GPL/LGPL alternative is selected for the shipped release.

| Family | Redistribution action |
| --- | --- |
| MIT, ISC, BSD-2/3-Clause | Preserve copyright, permission/conditions and disclaimer text; no endorsement by upstream authors. |
| Apache-2.0 | Ship license and attribution texts; mark modified TrustTunnel files; preserve applicable NOTICE files. |
| Unicode-3.0 | Ship copyright/permission/disclaimer with documentation; no use of authors' names for promotion. |
| CC0-1.0 | Preserve the supplied waiver/fallback license and limitations; do not imply trademark or patent rights. |
| Legacy OpenSSL/SSLeay in native components | Preserve original conditions and acknowledgments in NOTICE, README, release notes and binary documentation, including advertising acknowledgments. |

The collector includes all LICENSE/NOTICE/AUTHORS/COPYRIGHT/COPYING files found
in the exact downloaded package sources, including nested native sources.
Supplemental notices are pinned to source commits and file hashes. The 548-file
baseline was reconciled against the resolved package identities and reviewed
license families; future text, identity or license-expression changes fail
`scripts/license_review.py`. Do not satisfy the gate by copying an old notice
onto a changed dependency. Review new terms before updating the record.

## Native and crypto components

- **AWS-LC:** preserve the aws-lc-rs/sys outer ISC terms, full AWS-LC license
  (Apache/ISC choices, Apache-derived OpenSSL, MIT Fiat, BSD-3 Jitter Entropy,
  s2n-bignum and ML-KEM/ML-DSA attributions), and nested Fiat license. The AWS-LC
  file explicitly selects BSD rather than GPL for Jitter Entropy. Its supplied
  full texts and copyrights remain intact, regardless of which optional code
  paths the Linux binary links.
- **BoringSSL / boring-sys / quiche:** outer crate metadata does not describe all
  bundled components. Preserve both original BoringSSL trees and quiche's copy,
  including OpenSSL, SSLeay, ISC/MIT and associated attributions. `NOTICE` repeats
  the OpenSSL, Eric Young and Tim Hudson acknowledgments. Acknowledgments must
  accompany future advertising describing these components' use/features.
- **ring:** preserve Apache-2.0, ISC other-bits, BoringSSL and Fiat notices,
  including the embedded support-code notices; no claim that the outer crate's
  expression replaces those terms.
- **SQLite:** the enabled rusqlite `bundled` feature uses SQLite, not SQLCipher.
  SQLite deliverable code is public domain per the
  [SQLite authors](https://www.sqlite.org/copyright.html). Preserve the wrapper's
  MIT license and the supplied SQLCipher notice conservatively, without claiming
  SQLCipher encryption is enabled. Credential encryption uses the separate
  SolarTT key and ChaCha20-Poly1305, not database-wide encryption.
- Official TrustTunnel CLI and Caddy compatibility fixtures are test inputs only;
  their executable files are not included in the distributed package.

## TrustTunnel modifications and source availability

SolarTT-UI is Apache-2.0 and identifies the exact TrustTunnel upstream commit,
archive digest and managed patch. `prepare_upstream.py` adds a prominent
SolarTT modification notice to every file touched by the patches while retaining
original license/copyright text. Upstream supplies LICENSE and no root NOTICE.
The source archive includes the reconstruction scripts and patches; the pinned
TrustTunnel sources are downloaded and checksum-verified during reconstruction.

Both binary formats contain LICENSE, NOTICE, the complete third-party tree and
this review record. Published checksums and build.json bind the release assets
to the source commit and upstream pin. These are provenance/completeness checks;
they do not establish a legal certification, reproducible binary builds, absence
of vulnerabilities, or suitability for an untrusted production deployment.

## Security maintenance review — 2026-10-20

`rustls-webpki` advances from 0.103.15 to 0.103.16 to address
[RUSTSEC-2026-0382](https://rustsec.org/advisories/RUSTSEC-2026-0382.html)
([upstream fix](https://github.com/rustls/webpki/pull/546)). The update rejects
certificate paths containing known distrusted emSign public keys. Certificate
chains using those keys are intentionally no longer accepted; this is a change
to certificate verification, not a claim that an installed endpoint is exploitable.

Both crate archives were independently downloaded from crates.io and their
SHA-256 values checked against the crates.io index. The 0.103.16 archive digest is
`4443b1b6d39d7c663139942cc4558262562d2c84123bb6282ef177009ca8b281`.
The declared ISC license and the exact notice inventory remain unchanged:
`LICENSE` SHA-256 is
`5b698ca13897be3afdb7174256fa1574f8c6892b8bea1a66dd6469d3fe27885a`.
The old and new index records have identical dependency requirements, features
and minimum Rust version. No other resolved package is changed by this update.
The exact review record changes only this package identity; the historical
2026-10-15 inventory remains a record of its original build.

Locked resolution, full notice collection and compatibility regressions must
pass CI before release. Updating this source lockfile does not update existing
alpha.5 packages or installed nodes. A package release and any production
installation remain separate reviewed operations.

## SQLite security maintenance review — 2026-11-09

[RUSTSEC-2026-0459](https://rustsec.org/advisories/RUSTSEC-2026-0459.html)
affects the SQLite bundled by `libsqlite3-sys` before 0.39.0. Opening a crafted
database and sibling WAL with different page sizes can expose uninitialized
page-cache bytes. The fix requires a new Rusqlite minor line, so the automated
patch policy correctly produced the report-only
[manual task](dependency-updates/e296bd46e2ef3be6c5375d1c.json). That historical
report is not the dependency fix.

This manual update selects `rusqlite` 0.41.1 and `libsqlite3-sys` 0.39.1, bundling
SQLite 3.54.1. Their declared minimum Rust versions, 1.89 and 1.88 respectively,
fit the project's pinned Rust 1.95 toolchain. The enabled features remain bundled
SQLite and backup support; `cache` and `fallible_uint` explicitly preserve the old
statement-cache and fallible unsigned-integer conversions. Default features are
disabled to avoid enabling the new, unused WASM SQLite backend. SQLCipher is not
enabled. The backup call uses the new `MAIN_DB` name and a typed absent callback;
no schema, policy JSON or quota migration is introduced by this update.

The graph replaces `hashlink` 0.9.1 with 0.12.2 and adds `foldhash` 0.2.0.
`ahash` 0.8.12 and `hashbrown` 0.14.5 become unnecessary and are removed;
`hashbrown` 0.17.1 is reused. Existing unrelated package versions stay pinned.
The complete inventory is now **296 packages and 544 exact notice files**.

| Changed package | Selected license | Preserved notice inventory |
| --- | --- | --- |
| rusqlite 0.41.1 | MIT | Supplied LICENSE, including the rusqlite developers' attribution |
| libsqlite3-sys 0.39.1 | MIT | Supplied LICENSE; the old in-crate SQLCipher source/notice is absent from the new archive |
| hashlink 0.12.2 | MIT | Both MIT and Apache-2.0 texts, byte-identical to the earlier hashlink review |
| foldhash 0.2.0 | Zlib | Full origin, modification-marking and notice-preservation conditions |

All four archives were independently downloaded and their SHA256 values checked
against the runner-generated Cargo.lock. Their exact declared expressions,
notice inventories and bytes were reconciled with the runner's collector before
updating `upstream/license-review.json`. The new Rusqlite/sys LICENSE files have
SHA256 `c10c1f27337546471e5f7e4e97fdd398b35b9d4e126115dcd22de8d8e65abf6f`;
the foldhash LICENSE has SHA256
`b1181a40b2a7b25cf66fd01481713bc1005df082c53ef73e851e55071b102744`.
SQLite's public-domain status and the requirement to preserve wrapper notices
continue to apply. No old license text is substituted into a new package.

The security gate must audit the corrected lockfile, and the runtime regression
checks that the linked SQLite version includes the 3.54.0 fix. Policy/storage,
backup/restore and every published-baseline upgrade/rollback gate must pass on
disposable GitHub runners before release. Updating these sources does not update
published packages or installed agents; release and installation remain separate
reviewed actions.
