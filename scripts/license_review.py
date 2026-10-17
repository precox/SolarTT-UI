#!/usr/bin/env python3
"""Require the exact reviewed dependency notices before binary redistribution."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(notices, review):
    manifest = json.loads((notices / "manifest.json").read_text())
    if manifest["missing_license"]:
        raise ValueError("Incomplete license inventory")
    expected = {(p["name"], p["version"]): p for p in review["packages"]}
    actual = {(p["name"], p["version"]): p for p in manifest["packages"]}
    if len(expected) != len(review["packages"]) or len(actual) != len(manifest["packages"]) or expected.keys() != actual.keys():
        raise ValueError("Dependency set changed; review required")
    count = 0
    for identity, package in actual.items():
        approved = expected[identity]
        if package["license"] != approved["declared_license"] or not approved["selected_license"]:
            raise ValueError("License expression changed; review required")
        if len(package["notices"]) != len(set(package["notices"])) or set(package["notices"]) != approved["notices_sha256"].keys():
            raise ValueError("Notice inventory changed; review required")
        for name, digest in approved["notices_sha256"].items():
            path = notices / f"{identity[0]}-{identity[1]}" / name
            if not path.resolve().is_relative_to(notices.resolve()) or path.is_symlink():
                raise ValueError("Unsafe notice path")
            data = path.read_bytes()
            if not data or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("Notice text changed; review required")
            count += 1
    return {"packages": len(actual), "notices": count, "status": "PASS",
            "scope": "Exact reviewed license choices and preserved attribution texts; not legal advice"}


def main():
    notices = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist/third-party"
    review = json.loads((ROOT / "upstream/license-review.json").read_text())
    result = verify(notices, review)
    (notices.parent / "license-review-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Redistribution review: {result['packages']} packages, {result['notices']} exact notice files: PASS")


if __name__ == "__main__":
    main()
