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
