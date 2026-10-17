# Maintaining an alpha release

Only a maintainer with explicit publication authorization should push release
tags. The CI workflow automatically publishes matching alpha tags after all
prerequisites succeed; ordinary branch builds never publish a release.

TrustTunnel dependency updates begin with the separate
[upstream maintenance process](upstream-maintenance.md). Its watcher files tasks;
patch porting, compatibility review and all release gates still apply.

1. Update the workspace version and all six SolarTT entries in Cargo.lock.
   Keep the upstream/library pins explicit; never regenerate dependency versions
   merely to bump the SolarTT version. Add dated changelog and
   `docs/releases/vVERSION.md` notes with known limitations and upgrade caveats.
2. For dependency changes, collect exact notices and review actual obligations
   before editing `upstream/license-review.json`. Preserve all original texts
   and any required advertising/redistribution acknowledgments. Run the
   source/history/dependency scan and complete CI on a topic branch.
3. Integrate into `main` through a reviewed PR or an explicitly authorized
   fast-forward. Verify GitHub private vulnerability reporting is enabled.
4. Create a unique annotated tag whose version matches Cargo.toml, then push it.
   The tag must point to a commit contained in `main`. Use an alpha tag such as
   `v0.1.0-alpha.5`; stable tags are intentionally rejected by the alpha publisher.
5. The tagged CI build runs six prerequisite jobs. Only the publish job receives
   `contents: write`. It checks source/build/tag identity, asset checksums,
   successful prerequisites and private reporting before creating a draft.
   Uploads are verified before the draft becomes a public **prerelease**.
6. Check the actual Releases page, prerelease flag, asset list and public download
   checksums. Verify build.json's source commit against the resolved tag and the
   release-tests.json workflow link. CI artifacts expire; release assets are the
   permanent download location.

An interrupted draft can resume only with identical assets; conflicting files
fail without replacement. Never force-move a published tag or silently overwrite
an asset. Publish a new alpha version for a correction. Do not promote to stable
until the separately recorded field gates have passed.

## Test boundaries

Heavy compilation and disposable installation tests run on GitHub runners.
`package_smoke.py`, `pilot_upgrade.py`, browser acceptance and the minimal-runtime
fixture must not run against an operator's shared production host. Do not fake
`GITHUB_ACTIONS` or remove guards. The minimal container exercises runtime
processes without a build SDK; the separate GitHub Ubuntu VM exercises systemd
installation/upgrade/removal. Neither is real Android/network/capacity acceptance.

Publishing a GitHub release does not authorize installing it over a live VPN,
rotating owner keys, destructive quota/revoke tests or replacing a host proxy.
Coordinate that operational rollout separately.

Public filenames must use only ASCII letters, digits, dots, underscores and
hyphens. Debian version tildes belong in package metadata, not GitHub asset
filenames. The publisher checks GitHub's returned name before publication.
`docs/releases/withdrawn.json` identifies known withdrawn releases by exact source
commit; replacement publication preserves their assets/tag and marks them draft
(or clearly withdrawn if the repository made that release immutable).
