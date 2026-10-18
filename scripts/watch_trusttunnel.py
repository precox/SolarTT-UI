#!/usr/bin/env python3
"""Detect stable TrustTunnel releases; optionally file tasks, never update code."""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import urllib.parse

from github_api import DOWNSTREAM, GitHubAPI, GitHubError as WatchError

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "TrustTunnel/TrustTunnel"
SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def stable_version(tag):
    """Conservative stable SemVer subset: no prerelease/build suffix or leading zeros."""
    match = VERSION.fullmatch(tag) if isinstance(tag, str) else None
    return tuple(map(int, match.groups())) if match else None


@dataclass(frozen=True)
class Release:
    version: tuple
    tag: str
    published_at: str

    @property
    def canonical(self):
        return "v" + ".".join(map(str, self.version))

    @property
    def url(self):
        return f"https://github.com/{UPSTREAM}/releases/tag/{self.tag}"


class GitHub(GitHubAPI):
    def commit(self, tag):
        value = self.request("GET", f"/repos/{UPSTREAM}/commits/" + urllib.parse.quote(tag, safe=""))
        if not isinstance(value, dict) or not isinstance(value.get("sha"), str) or not SHA.fullmatch(value["sha"]):
            raise WatchError(f"Cannot resolve upstream tag {tag} to a full commit")
        # The commits API peels annotated tags; target_commitish may be a branch
        # and is deliberately never used as evidence of pin identity.
        return value["sha"]


def stable_releases(items):
    versions = {}
    for item in items:
        if type(item.get("draft")) is not bool or type(item.get("prerelease")) is not bool:
            raise WatchError("Release response lacks draft/prerelease flags")
        version = stable_version(item.get("tag_name"))
        if item["draft"] or item["prerelease"] or version is None:
            continue
        published = item.get("published_at")
        if not isinstance(published, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", published):
            raise WatchError("Stable release has no valid publication timestamp")
        release = Release(version, item["tag_name"], published)
        # v1.2.3 and 1.2.3 are one version. Resolve any ambiguous alias manually.
        if version in versions and versions[version] != release:
            raise WatchError(f"Ambiguous upstream release version {release.canonical}")
        versions[version] = release
    return sorted(versions.values(), key=lambda release: release.version, reverse=True)


def issue_title(release):
    return f"upstream: review TrustTunnel {release.canonical}"


def issue_marker(release):
    return f"<!-- solartt-upstream-watch:{UPSTREAM}:{release.canonical} -->"


def already_tracked(release, issues):
    return any("pull_request" not in issue and (
        issue.get("title") == issue_title(release)
        or issue_marker(release) in (issue.get("body") or "").splitlines()
    ) for issue in issues)


def issue_body(current, proposed, pin, commit):
    return f"""{issue_marker(proposed)}
A new stable TrustTunnel release needs a compatibility review for SolarTT-UI.

- Release: [{proposed.canonical}]({proposed.url}) (published {proposed.published_at}).
- Current upstream: [{current.canonical}]({current.url}), commit `{pin['commit']}`.
- Current archive SHA256: `{pin['archive_sha256']}`.
- Proposed upstream: [{proposed.canonical}]({proposed.url}), observed commit `{commit}`.
- [Compare pinned source with proposed source](https://github.com/{UPSTREAM}/compare/{pin['commit']}...{commit}).
- Review branch: `upstream/trusttunnel-{proposed.canonical}`.
- [Prepare the update PR](https://github.com/{DOWNSTREAM}/compare/main...upstream/trusttunnel-{proposed.canonical}?expand=1&template=upstream-update.md) after pushing that branch; complete the maintenance template.

This task records discovery only. The proposed commit is an observation, not a
reviewed pin or an archive checksum. SolarTT's managed agent includes
`upstream/0001-managed-policy.patch`; an official binary cannot replace it.

- [ ] Review changes, protocol/client/configuration compatibility and dependencies.
- [ ] Port the managed patch; review pin, verified archive SHA256, lockfiles and licenses.
- [ ] Pass full CI, including the alpha.5 managed H2 durable-lease regression
      (failure before the fix, successful download after), quotas and revoke A
      while B's streams survive.
- [ ] Open and review a PR, then release a new SolarTT version.
- [ ] Coordinate Riga installation separately with a backup and recovery plan.

Follow [the maintenance process](https://github.com/{DOWNSTREAM}/blob/main/docs/upstream-maintenance.md).
No patch port, merge, package release or server installation is automated.
Keep the hidden marker when editing this issue. Closed issues also suppress repeats.
"""


def watch(api, pin, create=False):
    if (not isinstance(pin, dict) or pin.get("repository") != UPSTREAM
            or stable_version(pin.get("tag")) is None
            or not isinstance(pin.get("commit"), str) or not SHA.fullmatch(pin["commit"])
            or not isinstance(pin.get("archive_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", pin["archive_sha256"])):
        raise WatchError("Invalid TrustTunnel pin")
    releases = stable_releases(api.pages(f"/repos/{UPSTREAM}/releases"))
    current = next((release for release in releases if release.tag == pin["tag"]), None)
    if current is None:
        raise WatchError("Pinned tag is not a published stable release; review pin/tags manually")
    if api.commit(current.tag) != pin["commit"]:
        raise WatchError("Pinned tag does not match the pinned commit; review pin/tags manually")
    candidates = sorted((r for r in releases if r.version > current.version), key=lambda r: r.version)
    # Finish all discovery/validation before the first write. An API failure
    # must never masquerade as 'no new releases' or an empty deduplication set.
    resolved = {release.tag: api.commit(release.tag) for release in candidates}
    issues = list(api.pages(f"/repos/{DOWNSTREAM}/issues?state=all")) if candidates else []
    result = {"current": current.canonical, "current_commit": pin["commit"],
              "mode": "create" if create else "dry-run", "releases": []}
    for release in candidates:
        tracked = already_tracked(release, issues)
        entry = {"version": release.canonical, "url": release.url,
                 "commit": resolved[release.tag], "status": "tracked" if tracked else "would-create"}
        if create and not tracked:
            payload = {"title": issue_title(release),
                       "body": issue_body(current, release, pin, resolved[release.tag])}
            response = api.request("POST", f"/repos/{DOWNSTREAM}/issues", payload)
            if not isinstance(response, dict) or type(response.get("number")) is not int:
                raise WatchError("Invalid issue creation response; rerun to reconcile before retrying")
            entry.update(status="created", issue=response["number"])
            issues.append(payload)
        result["releases"].append(entry)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create-issues", action="store_true", help="write issues (default is read-only)")
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN")
    if args.create_issues and not token:
        parser.error("--create-issues requires GH_TOKEN with issues:write for " + DOWNSTREAM)
    try:
        pin = json.loads((ROOT / "upstream/pin.json").read_text())
        result = watch(GitHub(token), pin, create=args.create_issues)
    except (WatchError, OSError, ValueError) as error:
        raise SystemExit(str(error)) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
