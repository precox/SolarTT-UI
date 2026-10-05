#!/usr/bin/env python3
"""Collect dependency metadata and license notices from the exact resolved sources.

Requires cargo metadata JSON on stdin; run in CI after dependencies are downloaded.
Inspect the manifest's missing_license entries before releasing.
"""
import json
import hashlib
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
    supplements = {(p["name"], p["version"]): p for p in
        json.loads((ROOT / "upstream/notices/manifest.json").read_text())["packages"]}
    for package in sorted(metadata["packages"], key=lambda p: (p["name"],p["version"])):
        source = Path(package["manifest_path"]).parent.resolve()
        is_upstream = source.is_relative_to(ROOT / ".upstream")
        if package["name"].startswith("solartt-"):
            continue
        license_name = package.get("license") or ("Apache-2.0" if is_upstream else None)
        folder = output / f"{package['name']}-{package['version']}"
        folder.mkdir()
        candidates = [p for p in source.rglob("*") if p.is_file() and
            p.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS", "COPYRIGHT"))]
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
        supplemental = supplements.get((package["name"], package["version"]))
        if supplemental:
            vcs = source / ".cargo_vcs_info.json"
            if vcs.is_file() and json.loads(vcs.read_text())["git"]["sha1"] != supplemental["commit"]:
                raise SystemExit("Supplemental notices do not match dependency source commit")
            for notice in supplemental["sources"]:
                relative = Path(notice["file"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise SystemExit("Unsafe supplemental notice path")
                original = ROOT / "upstream/notices" / folder.name / relative
                data = original.read_bytes()
                if hashlib.sha256(data).hexdigest() != notice["sha256"]:
                    raise SystemExit("Supplemental notice checksum mismatch")
                target = folder / "supplemental" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                paths.append(str(target.relative_to(folder)))
        if not license_name or not paths:
            missing.append(f"{package['name']} {package['version']}")
        records.append({"name":package["name"],"version":package["version"],"license":license_name,
            "source":package.get("source") or ("pinned TrustTunnel" if is_upstream else "local"),"notices":paths,
            "supplemental_notice_sources": supplemental["sources"] if supplemental else []})
    (output / "manifest.json").write_text(json.dumps({"packages":records,"missing_license":missing},indent=2)+"\n")
    print(f"Collected notices for {len(records)} dependencies; {len(missing)} require review")
    for package in missing:
        print(f"Missing license metadata or notice: {package}")
    if missing:
        raise SystemExit("Dependency notices are incomplete; refusing packaging")

if __name__ == "__main__":
    main()
