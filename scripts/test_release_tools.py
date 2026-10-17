"""Release guard regressions; temporary synthetic manifests only."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from license_review import verify
from publish_alpha import checked_manifest, validate_identity, verify_uploaded_asset


class LicenseReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.notice = self.root / 'fixture-1/LICENSE'
        self.notice.parent.mkdir()
        self.notice.write_bytes(b'Synthetic fixture license')
        self.package = {'name':'fixture','version':'1','license':'MIT','notices':['LICENSE']}
        self.review = {'packages':[{'name':'fixture','version':'1','declared_license':'MIT',
            'selected_license':'MIT','notices_sha256':{'LICENSE':hashlib.sha256(self.notice.read_bytes()).hexdigest()}}]}
        self.write_manifest()

    def write_manifest(self):
        (self.root / 'manifest.json').write_text(json.dumps({'packages':[self.package],'missing_license':[]}))

    def test_exact_review_passes(self):
        self.assertEqual(verify(self.root,self.review)['notices'],1)

    def test_changed_license_text_requires_review(self):
        self.notice.write_bytes(b'Changed obligations')
        with self.assertRaises(ValueError):
            verify(self.root,self.review)

    def test_changed_expression_and_version_require_review(self):
        for field, value in [('license','GPL-3.0-only'),('version','2')]:
            with self.subTest(field=field):
                old = self.package[field]; self.package[field] = value; self.write_manifest()
                with self.assertRaises(ValueError):
                    verify(self.root,self.review)
                self.package[field] = old

    def test_missing_or_extra_notice_requires_review(self):
        for notices in [[],['LICENSE','NOTICE']]:
            self.package['notices'] = notices; self.write_manifest()
            with self.assertRaises(ValueError):
                verify(self.root,self.review)


class PublicationGuards(unittest.TestCase):
    def test_normalized_filename_is_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'solartt_0.1~alpha3.deb'
            path.write_bytes(b'synthetic package')
            uploaded = {'name':path.name,'size':path.stat().st_size,'state':'uploaded',
                        'digest':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()}
            verify_uploaded_asset(path,uploaded)
            uploaded['name'] = path.name.replace('~','.')
            with self.assertRaises(ValueError):
                verify_uploaded_asset(path,uploaded)

    def test_exact_alpha_identity(self):
        commit = 'a'*40
        validate_identity('v0.1.0-alpha.3',commit,{'version':'0.1.0-alpha.3','source_commit':commit},'0.1.0-alpha.3')

    def test_stable_tag_or_different_source_rejected(self):
        commit = 'a'*40
        for tag, source in [('v0.1.0',commit),('v0.1.0-alpha.3','b'*40)]:
            with self.subTest(tag=tag, source=source):
                with self.assertRaises(ValueError):
                    validate_identity(tag,commit,{'version':'0.1.0-alpha.3','source_commit':source},'0.1.0-alpha.3')

    def test_manifest_rejects_tamper_duplicates_and_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'package').write_bytes(b'fixture')
            digest = hashlib.sha256(b'fixture').hexdigest()
            line = f'{digest}  package\n'
            (root/'SHA256SUMS').write_text(line)
            self.assertEqual(checked_manifest(root), {'package'})
            for text in [line+line, f'{digest}  ../package\n', f'{"0"*64}  package\n']:
                (root/'SHA256SUMS').write_text(text)
                with self.assertRaises(ValueError):
                    checked_manifest(root)


if __name__ == '__main__':
    unittest.main()
