# Tokio / Rustix advisory review — 12 November 2026

## Decision and scope

**No affected execution path was identified in the supported SolarTT managed
mode for the reviewed source and lockfile.** This is scoped applicability
analysis, not a claim that the libraries or standalone upstream ICMP code are
universally safe. Keep both warnings visible. The release preparation retains
the tested dependency graph; patched library versions are candidates for a
separate maintenance update and its own compatibility/CI review.

Reviewed basis: published `v0.1.1-alpha.1`, source
`690b621074896cf6758f12ea5ff612f21197d82a`; the stable preparation has identical
runtime code, dependency versions and managed patch. Upstream TrustTunnel remains
`fab5b8353a19332f935fa30869307d37d4a898d1`, reconstructed from its checksum-pinned
archive and the existing managed patch. No library, upstream patch, supported
configuration, scanner rule or advisory ignore list is changed by this review.

The [structured review](releases/v0.1.1-advisory-review.json) records exact
archives, the caller checks and the finite binary probe. Stable publication
approval and production rollout remain separate owner decisions.

## Tokio 1.53.2 — RUSTSEC-2026-0386

The [advisory](https://rustsec.org/advisories/RUSTSEC-2026-0386.html) concerns
descriptor ownership/lifetime safety in `tokio::io::unix::AsyncFd` constructors.
The pinned upstream ICMP implementation does contain `AsyncFd<libc::c_int>` and
manual descriptor cleanup, so classifying the API as entirely unused would be
incorrect. No exploit was attempted or demonstrated.

The supported managed executable blocks that path:

1. [Agent configuration loading](../crates/agent/src/main.rs) rejects both
   `settings.get_icmp().is_some()` and enabled `ping_enable`. This is an enforced
   rejection, not merely a default setting.
2. The executable calls `load(&config)?` before reading the data key, opening its
   policy database or constructing `Core::new_managed`.
3. With ICMP settings absent, the pinned upstream constructs no ICMP forwarder;
   its ICMP listener returns immediately. TLS SIGHUP reloads TLS hosts only and
   does not replace core endpoint settings.
4. Source inspection found no `AsyncFd` references in SolarTT's crates or the
   seven registry packages that directly depend on Tokio in this lockfile:
   axum, h2, hyper, hyper-util, tokio-rustls, tokio-util and tower. Their exact
   source archives were verified against locked checksums. The upstream ICMP
   module was the only reference in the reviewed project/upstream runtime source.

An additional finite, unprivileged probe exercised the exact published alpha
agent, whose binary bytes were matched to the checksum-verified deb:

| Synthetic configuration | Observed result |
| --- | --- |
| Supported endpoint settings, deliberately missing TLS-host file | Passed the managed settings guard and failed at the expected missing-file stage |
| Same settings plus an empty `[icmp]` section | Rejected with the exact managed-endpoint guard diagnostic |
| Same settings with `ping_enable = true` | Rejected with the exact managed-endpoint guard diagnostic |

All processes exited with code 1 as expected. The deliberately absent database,
key and control socket were not created. No package was installed, service
started, real profile used or production configuration read/written. These are
operator-run refusal probes, not a newly added CI regression or live VPN test.

Tokio **1.53.3** is a patched candidate in the same minor series. Its verified
archive retains the Rust 1.71 minimum and identical MIT notice bytes. Its
`AsyncFd::new` is deprecated and forwards to the explicit unsafe registration
API: a version bump alone must not be presented as repairing an application's
incorrect raw-descriptor lifetime. Before supporting ICMP, review descriptor
ownership/deregistration and add appropriate runtime regression coverage. See
the [Tokio change](https://github.com/tokio-rs/tokio/pull/8587).

## Rustix 1.1.5 — RUSTSEC-2026-0486

The [advisory](https://rustsec.org/advisories/RUSTSEC-2026-0486.html) concerns
zero-length buffers passed to the get/list extended-attribute functions. The
precise lockfile edges matter:

- `tempfile` **3.27.0** → `rustix` **1.1.5**, the affected version.
- `procfs` **0.17.0** → `rustix` **0.38.44**, outside the affected 1.x range.

`tempfile` is the only immediate consumer of Rustix 1.1.5 in this lockfile.
Its checksum-verified source uses file operations/constants such as rename,
unlink, fstat and O_TMPFILE, not the six affected get/list xattr functions.
Its source also contains no public Rustix re-export. SolarTT runtime source has
no direct affected xattr call. Therefore this reviewed dependency path does not
call the API described by the advisory. This is not a blanket statement about
all Rustix filesystem operations or future dependency graphs.

Rustix **1.1.6** is the patched candidate; its verified archive retains Rust 1.65,
the same declared license expression and identical license-file bytes. The
[upstream fix](https://github.com/bytecodealliance/rustix/commit/8e6aaa6713d2bb64b1fdd8c472e3a32a10a76d70)
handles empty buffers and adds explicit size-query functions. A later update
must still be resolved/tested on a disposable runner and recheck the resulting
dependency and redistribution inventory; this review does not claim that
resolution or candidate CI has already been performed.

## Why CI is green and follow-up boundary

RustSec labels these records informational `unsound`; cargo-audit reports them
under warnings, outside its vulnerability list. The project's current source
audit and automatic dependency proposal policy preserve those warnings and do
not treat them as ordinary vulnerability-list entries. Successful CI is thus
consistent with visible warnings and does not replace this applicability review.

The review does not remove a warning, install an update, alter the managed
patch or accept an arbitrary future graph. Reopen it if ICMP/endpoint validation,
descriptor handling, tempfile/Rustix consumers, Tokio consumers, supported
platforms or the locked versions change. The inherited unmaintained
`rustls-pemfile` notice remains a separate maintenance warning.
