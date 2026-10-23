"""Release guard regressions; temporary synthetic manifests only."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from license_review import verify
from publish_alpha import checked_manifest, validate_identity, validate_upgrade_report, verify_uploaded_asset, release_is_prerelease, validate_stable_acceptance


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
    def test_upgrade_report_must_match_candidate_and_published_baseline(self):
        baseline = {'commit':'a'*40, 'version':'0.1.0-alpha.5', 'assets_sha256':{'old.deb':'b'*64}}
        report = {'status':'PASS', 'candidate_commit':'c'*40, 'candidate_package_sha256':'d'*64,
                  'baseline_commit':baseline['commit'], 'baseline_version':baseline['version'],
                  'baseline_package_sha256':'b'*64}
        validate_upgrade_report(report, 'c'*40, 'd'*64, baseline)
        for key in report:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_upgrade_report({**report, key:'wrong'}, 'c'*40, 'd'*64, baseline)

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

    def test_mismatched_version_or_different_source_rejected(self):
        commit = 'a'*40
        for tag, source in [('v0.1.0',commit),('v0.1.0-alpha.3','b'*40)]:
            with self.subTest(tag=tag, source=source):
                with self.assertRaises(ValueError):
                    validate_identity(tag,commit,{'version':'0.1.0-alpha.3','source_commit':source},'0.1.0-alpha.3')

    def test_release_channel_and_exact_stable_identity(self):
        self.assertFalse(release_is_prerelease('v0.1.0'))
        self.assertTrue(release_is_prerelease('v0.1.0-alpha.6'))
        commit = 'a'*40
        validate_identity('v0.1.0', commit, {'version':'0.1.0', 'source_commit':commit}, '0.1.0')
        for tag in ['0.1.0', 'v01.1.0', 'v0.01.0', 'v0.1.00', 'v0.1.0-alpha.06',
                    'v0.1.0-rc.1', 'v0.1.0+build', '../v0.1.0', 'v0.1.0\n']:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release_is_prerelease(tag)

    def test_stable_requires_explicit_decision_and_honest_limits(self):
        record = {
            'version':'0.1.0', 'decision':'accepted_with_documented_limitations',
            'owner_accepted_limitations':True, 'network_reachability_guarantee':False,
            'advertised_client_capacity':False,
            'deferred_checks':{name:'Not yet verified' for name in
                ['real_certificate_replacement', 'independent_full_stack_restore', 'capacity_benchmark']},
            'observation':{'status':'complete', 'local_health_failures':0, 'collection_errors':0, 'samples':12},
            'local_restore':'PASS', 'acme_staging_dry_run':'PASS',
        }
        validate_stable_acceptance('v0.1.0', record)
        for key, value in [('version','0.1.1'), ('decision','pending'),
                           ('owner_accepted_limitations',False), ('owner_accepted_limitations',1),
                           ('network_reachability_guarantee',True), ('advertised_client_capacity',True),
                           ('local_restore','NOT VERIFIED'), ('acme_staging_dry_run','FAIL'),
                           ('observation',None), ('deferred_checks',[])]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_stable_acceptance('v0.1.0', {**record, key:value})
        for key, value in [('status','running'), ('local_health_failures',1),
                           ('collection_errors',1), ('samples',0), ('samples',True), ('samples','12')]:
            changed = copy.deepcopy(record)
            changed['observation'][key] = value
            with self.subTest(observation=key, value=value), self.assertRaises(ValueError):
                validate_stable_acceptance('v0.1.0', changed)
        for mutation in ['missing', 'empty', 'extra']:
            changed = copy.deepcopy(record)
            if mutation == 'missing':
                del changed['deferred_checks']['capacity_benchmark']
            elif mutation == 'empty':
                changed['deferred_checks']['capacity_benchmark'] = ' '
            else:
                changed['deferred_checks']['another_gate'] = 'Unverified'
            with self.subTest(deferral=mutation), self.assertRaises(ValueError):
                validate_stable_acceptance('v0.1.0', changed)
        with self.assertRaises(ValueError):
            validate_stable_acceptance('v0.1.0', None)
        validate_stable_acceptance('v0.1.0-alpha.7', {})

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
