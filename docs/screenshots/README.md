# Mobile panel previews

These PNGs show the shipped HTML/CSS/JavaScript at a 390 × 1060 CSS-pixel mobile
viewport (2× device scale). They are browser-rendered documentation previews,
not photographs of a phone or evidence of Android VPN compatibility.

All user names, usage totals, profile names and limits are synthetic. The
renderer starts a temporary loopback static server, substitutes an in-memory
read-only API, and blocks browser page requests other than the three UI assets.
It never starts the agent, reads a database, logs into the production panel,
exports profiles or uses any real credentials. The screenshots show Alex · Demo
and Sam · Demo, with a mock 100-GiB allowance and a three-profile limit.

Regenerate on a disposable development machine with Node 22 and Google Chrome:

```sh
node scripts/render_readme_previews.mjs
```

Or use **Actions → Render documentation previews → Run workflow**. The artifact
contains the two PNGs and a small provenance record; review the images before
copying them from `dist/readme-previews/` here. The helper workflow renders docs
only; it does not replace the build/security or upstream-watcher workflows.

The previews are distributed under the project's Apache-2.0 license.
