# Contributing

Use a topic branch and a pull request. Run formatting, clippy and tests. Add
regression tests for quota, authentication, cancellation or migration changes.
Never put working VPN credentials, private keys, access links, server backups
or user logs in commits or issues.

Changes to upstream belong in explicit patch files with a rationale and tests.
Keep web, calendar and SQLite policy out of protocol code. New dependencies
require a license review. Do not enable unsupported capabilities in the UI.

## Development setup

Use Rust 1.95.0 (pinned in `rust-toolchain.toml`) with rustfmt and clippy, Python 3,
a C/C++ compiler, CMake, pkg-config and libclang. JavaScript checks also require
Node. Prepare the pinned TrustTunnel source before running the workspace tests:

```sh
python3 scripts/prepare_upstream.py
cargo fmt --all --check
cargo clippy --locked -p solartt-control-api -p solartt-policy -p solartt-profile-export -p solartt-panel -p solartt-admin --all-targets -- -D warnings
cargo test --locked
node --test scripts/panel_state_tests.mjs
```

The default workspace tests exclude the native agent. With the full native
toolchain installed, run its tests separately:

```sh
cargo test --locked -p solartt-agent -- --test-threads=1
```

Heavy native builds belong on a development machine or in CI. Installed-package,
browser, proxy and upgrade acceptance require additional fixtures; follow
[the CI workflow](.github/workflows/ci.yml) on a disposable runner. Do not bypass
the guards in `package_smoke.py` or `pilot_upgrade.py` to run them on a shared or
production host.

## Releases

Release maintainers: follow [the alpha publication procedure](docs/releasing.md).
An authorized alpha tag starts gated publication; stable field gates remain a
separate iteration. Never run disposable CI lifecycle tests on a production node.

## Contribution license

SolarTT-UI is licensed under [Apache-2.0](LICENSE). Unless explicitly stated
otherwise, contributions submitted for inclusion are provided under the same
license, as described in section 5. Preserve existing copyright and attribution
notices; the project license does not replace dependencies' individual terms.
