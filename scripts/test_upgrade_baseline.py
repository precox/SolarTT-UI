"""Baseline integrity checks using temporary synthetic files, no install/extract."""
import hashlib
import json
import tempfile
import unittest
import subprocess
from pathlib import Path

from prepare_alpha5_baseline import verify
from prepare_acceptance_kit import copy_public_inputs


class BaselineTests(unittest.TestCase):
    def test_kit_copies_tracked_public_inputs_without_untracked_private_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "docs").mkdir()
            (root / "examples").mkdir()
            (root / "docs/public.md").write_text("public fixture")
            (root / "examples/public.toml").write_text("public fixture")
            subprocess.run(["git", "add", "docs/public.md", "examples/public.toml"], cwd=root, check=True)
            (root / "docs/untracked-private.md").write_text("private fixture")
            (root / "examples/untracked-private.toml").write_text("private fixture")
            destination = Path(folder) / "kit"
            copy_public_inputs(root, destination)
            self.assertEqual(sorted(p.relative_to(destination).as_posix()
                                    for p in destination.rglob("*") if p.is_file()),
                             ["docs/public.md", "examples/public.toml"])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.commit = "a" * 40
        (self.root / "fixture.deb").write_bytes(b"synthetic package, never installed")
        self.metadata = {"version": "0.1.0-alpha.5", "source_commit": self.commit}
        self.prepare()

    def prepare(self):
        (self.root / "build.json").write_text(json.dumps(self.metadata))
        hashes = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                  for name in ("fixture.deb", "build.json")}
        (self.root / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in hashes.items()))
        hashes["SHA256SUMS"] = hashlib.sha256((self.root / "SHA256SUMS").read_bytes()).hexdigest()
        self.pin = {"version": "0.1.0-alpha.5", "commit": self.commit, "assets_sha256": hashes}

    def test_verified_public_package_selected(self):
        self.assertEqual(verify(self.root, self.pin), self.root / "fixture.deb")

    def test_alpha6_identity_is_independent_of_alpha5(self):
        self.metadata['version'] = '0.1.0-alpha.6'
        self.prepare()
        with self.assertRaises(ValueError):
            verify(self.root, self.pin)
        self.pin['version'] = '0.1.0-alpha.6'
        self.assertEqual(verify(self.root, self.pin), self.root / 'fixture.deb')

    def test_changed_package_or_metadata_or_manifest_is_rejected(self):
        for name in self.pin["assets_sha256"]:
            original = (self.root / name).read_bytes()
            with self.subTest(name=name):
                (self.root / name).write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    verify(self.root, self.pin)
                (self.root / name).write_bytes(original)

    def test_rehashed_wrong_source_or_version_is_rejected(self):
        for key, value in [("source_commit", "b" * 40), ("version", "0.1.0-alpha.1")]:
            with self.subTest(key=key):
                original = self.metadata[key]
                self.metadata[key] = value
                self.prepare()
                with self.assertRaises(ValueError):
                    verify(self.root, self.pin)
                self.metadata[key] = original

    def test_pinned_manifest_cannot_disagree_with_package_hash(self):
        (self.root / "SHA256SUMS").write_text("0" * 64 + "  fixture.deb\n")
        self.pin["assets_sha256"]["SHA256SUMS"] = hashlib.sha256((self.root / "SHA256SUMS").read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            verify(self.root, self.pin)


if __name__ == "__main__":
    unittest.main()
