"""Conservative, testable policy for public crates.io security patch updates."""
import hashlib
import io
import json
import re
import tarfile
import tomllib
import urllib.request

REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"
SHA = re.compile(r"[0-9a-f]{40}")
CRATE = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_-]{0,63}")
PRE = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
                     rf"(?:-({PRE}(?:\.{PRE})*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")


class ManualReview(RuntimeError):
    """A supported observation which cannot be fixed under the automatic policy."""


def version(value, stable=False):
    match = VERSION.fullmatch(value) if isinstance(value, str) else None
    if not match or (stable and match[4]):
        raise ManualReview("noncanonical_or_prerelease_version")
    # Accept complete SemVer identities in audit/report data, while keeping
    # automatic version selection narrower than Cargo's version grammar.
    if match[5]:
        raise ManualReview("build_metadata_requires_manual_review")
    pre = match[4]
    # Numeric prerelease identifiers sort before nonnumeric ones; a stable
    # version sorts after any prerelease of the same core version.
    suffix = ((2, ""),) if pre is None else tuple(
        (0, int(part)) if part.isdigit() else (1, part) for part in pre.split("."))
    return tuple(map(int, match.group(1, 2, 3))), suffix


def matches(candidate, requirement):
    if not isinstance(requirement, str):
        raise ManualReview("unsupported_advisory_range")
    for clause in requirement.split(","):
        match = re.fullmatch(r"\s*(>=|<=|>|<|=)\s*(\S+)\s*", clause)
        if not match:
            raise ManualReview("unsupported_advisory_range")
        left, right = version(candidate, stable=True), version(match[2])
        if not {">=": left >= right, "<=": left <= right, ">": left > right,
                "<": left < right, "=": left == right}[match[1]]:
            return False
    return True


def findings(report, returncode):
    try:
        database = report["database"]["last-commit"]
        values = report["vulnerabilities"]["list"]
        count = report["vulnerabilities"]["count"]
        if (not isinstance(database, str) or not SHA.fullmatch(database)
                or not isinstance(values, list) or type(count) is not int
                or count != len(values) or returncode != (1 if values else 0)):
            raise ValueError()
        result = []
        for item in values:
            name, current = item["package"]["name"], item["package"]["version"]
            advisory, patched = item["advisory"]["id"], item["versions"]["patched"]
            if (not isinstance(name, str) or not CRATE.fullmatch(name)
                    or not isinstance(current, str) or not VERSION.fullmatch(current)
                    or not isinstance(advisory, str) or not re.fullmatch(r"RUSTSEC-[0-9]{4}-[0-9]{4}", advisory)
                    or not isinstance(patched, list) or any(not isinstance(r, str) for r in patched)):
                raise ValueError()
            result.append({"package": name, "version": current, "advisory": advisory,
                           "patched": sorted(patched)})
        return database, sorted(result, key=lambda r: (r["package"], r["version"], r["advisory"]))
    except (KeyError, TypeError, ValueError):
        raise ValueError("Invalid cargo-audit response; never treat an audit error as healthy") from None


def download(url, limit=24 * 1024 * 1024):
    request = urllib.request.Request(url, headers={"User-Agent": "SolarTT-dependency-maintenance"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ManualReview("registry_object_exceeds_limit")
    return data


def index(name):
    if not isinstance(name, str) or not CRATE.fullmatch(name):
        raise ValueError("Invalid crate name")
    lower = name.lower()
    path = ("1/" + lower if len(lower) == 1 else "2/" + lower if len(lower) == 2
            else "3/" + lower[0] + "/" + lower if len(lower) == 3
            else lower[:2] + "/" + lower[2:4] + "/" + lower)
    records = [json.loads(line) for line in download("https://index.crates.io/" + path).splitlines()]
    if any(r.get("name", "").lower() != lower for r in records):
        raise ValueError("Registry identity mismatch")
    return {r["vers"]: r for r in records}


def choose_target(current, entries, observations):
    core = version(current, stable=True)[0]
    candidates = []
    for value, record in entries.items():
        try:
            candidate = version(value, stable=True)[0]
        except ManualReview:
            continue
        if record.get("yanked") is not False or candidate[:2] != core[:2] or candidate <= core:
            continue
        if all(any(matches(value, requirement) for requirement in observation["patched"])
               for observation in observations):
            candidates.append(value)
    if not candidates:
        raise ManualReview("no_supported_stable_patch")
    return min(candidates, key=lambda value: version(value, stable=True))


def review_target(name, current, target, entries, approved):
    old, new = entries[current], entries[target]
    keys = ("deps", "features", "features2", "rust_version")
    if any(old.get(key) != new.get(key) for key in keys):
        raise ManualReview("dependency_features_or_msrv_changed")
    checksum = new.get("cksum")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Invalid registry checksum")
    data = download(f"https://static.crates.io/crates/{name}/{name}-{target}.crate")
    if hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError("Crate checksum mismatch")
    notices = {}
    manifest = None
    prefix = f"{name}-{target}/"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        total = 0
        for member in archive:
            # No extraction; still reject links/traversals and duplicate notice
            # entries so the inspected bytes match the later notice collector.
            if (not member.name.startswith(prefix) or ".." in member.name.split("/")
                    or member.issym() or member.islnk()):
                raise ManualReview("unsupported_crate_archive")
            if not member.isfile():
                continue
            total += member.size
            if total > 128 * 1024 * 1024:
                raise ManualReview("crate_expansion_exceeds_limit")
            relative = member.name[len(prefix):]
            if relative == "Cargo.toml":
                manifest = tomllib.loads(archive.extractfile(member).read().decode())["package"]
            if relative.rsplit("/", 1)[-1].upper().startswith(
                    ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS", "COPYRIGHT")):
                if relative in notices:
                    raise ManualReview("duplicate_crate_notice")
                notices[relative] = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
    if not manifest or manifest.get("name") != name or manifest.get("version") != target:
        raise ValueError("Crate manifest identity mismatch")
    if (manifest.get("license") != approved["declared_license"]
            or manifest.get("license_file") or manifest.get("license-file") or not notices
            or notices != approved["notices_sha256"]):
        raise ManualReview("license_or_notice_review_required")
    return checksum


def validate_patch(old_lock, new_lock, old_review, new_review, target):
    """Also run in the privileged publisher, before any GitHub write."""
    old = tomllib.loads(old_lock)["package"]
    new = tomllib.loads(new_lock)["package"]
    expected = json.loads(json.dumps(old))
    selected = [p for p in expected if p["name"] == target["package"] and p["version"] == target["from"]]
    if len(selected) != 1 or selected[0].get("source") != REGISTRY:
        raise ManualReview("unsupported_dependency_source_or_identity")
    old_core = version(target["from"], stable=True)[0]
    new_core = version(target["to"], stable=True)[0]
    if new_core[:2] != old_core[:2] or new_core <= old_core:
        raise ValueError("Only increasing stable patch updates are allowed")
    if not re.fullmatch(r"[0-9a-f]{64}", target["checksum"]):
        raise ValueError("Invalid proposed checksum")
    selected[0].update(version=target["to"], checksum=target["checksum"])
    key = lambda p: (p["name"], p["version"], p.get("source", ""))
    if sorted(expected, key=key) != sorted(new, key=key):
        raise ManualReview("resolved_graph_changed")
    expected_review = json.loads(old_review)
    proposed_review = json.loads(new_review)
    records = [p for p in expected_review["packages"] if p["name"] == target["package"] and p["version"] == target["from"]]
    if len(records) != 1 or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", proposed_review.get("review_date", "")):
        raise ValueError("Invalid proposed review identity/date")
    records[0]["version"] = target["to"]
    expected_review["review_date"] = proposed_review["review_date"]
    if expected_review != proposed_review:
        raise ValueError("The updater cannot approve changed license texts or other packages")


def fingerprint(summary):
    identity = {key: summary[key] for key in ("before_lock_sha256", "findings", "decision", "reason", "target")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
