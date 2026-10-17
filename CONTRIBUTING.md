# Contributing

Use a topic branch and a pull request. Run formatting, clippy and tests. Add
regression tests for quota, authentication, cancellation or migration changes.
Never put working VPN credentials, private keys, access links, server backups
or user logs in commits or issues.

Changes to upstream belong in explicit patch files with a rationale and tests.
Keep web, calendar and SQLite policy out of protocol code. New dependencies
require a license review. Do not enable unsupported capabilities in the UI.

Release maintainers: follow [the alpha publication procedure](docs/releasing.md).
An authorized alpha tag starts gated publication; stable field gates remain a
separate iteration. Never run disposable CI lifecycle tests on a production node.
