#!/usr/bin/env python3
"""Collect dependency metadata and license notices from the exact resolved sources.

Requires cargo metadata JSON on stdin; run in CI after dependencies are downloaded.
Inspect the manifest's missing_license entries before releasing.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    metadata = json.load(sys.stdin)
    output = ROOT / "dist/third-party"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    records = []
    missing = []
    for package in sorted(metadata["packages"], key=lambda p: (p["name"],p["version"])):
        source = Path(package["manifest_path"]).parent.resolve()
        is_upstream = source.is_relative_to(ROOT / ".upstream")
        if package["name"].startswith("solartt-"):
            continue
        license_name = package.get("license") or ("Apache-2.0" if is_upstream else None)
        folder = output / f"{package['name']}-{package['version']}"
        folder.mkdir()
        candidates = [p for p in source.rglob("*") if p.is_file() and
            p.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE"))]
        if package.get("license_file"):
            candidates.append(source / package["license_file"])
        if is_upstream:
            candidates.append(ROOT / ".upstream/LICENSE")
        paths = []
        for path in sorted(set(candidates)):
            resolved = path.resolve()
            if not (resolved.is_relative_to(source) or resolved == ROOT / ".upstream/LICENSE"):
                raise SystemExit("License file escaped package source")
            relative = Path("UPSTREAM-LICENSE") if resolved == ROOT / ".upstream/LICENSE" else path.relative_to(source)
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path,target)
            paths.append(str(relative))
        if not license_name or not paths:
            missing.append(f"{package['name']} {package['version']}")
        records.append({"name":package["name"],"version":package["version"],"license":license_name,
            "source":package.get("source") or ("pinned TrustTunnel" if is_upstream else "local"),"notices":paths})
    (output / "manifest.json").write_text(json.dumps({"packages":records,"missing_license":missing},indent=2)+"\n")
    print(f"Collected notices for {len(records)} dependencies; {len(missing)} require review")
    for package in missing:
        print(f"Missing license metadata or notice: {package}")

if __name__ == "__main__":
    main()
