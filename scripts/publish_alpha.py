#!/usr/bin/env python3
"""Publish an exact successful alpha/stable tag build (GitHub CI only)."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_is_prerelease(tag):
    number = r'(?:0|[1-9][0-9]*)'
    if not re.fullmatch(rf'v{number}\.{number}\.{number}(?:-alpha\.{number})?', tag):
        raise ValueError('Expected a canonical stable or alpha release tag')
    return '-alpha.' in tag


def validate_identity(tag, commit, metadata, version):
    release_is_prerelease(tag)
    if tag != 'v' + version or metadata['version'] != version or metadata['source_commit'] != commit:
        raise ValueError('Tag/source/build identity mismatch')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid source identity')


def validate_stable_acceptance(tag, record):
    if release_is_prerelease(tag):
        return
    if not isinstance(record, dict):
        raise ValueError('Stable acceptance must be an object')
    deferred = {'real_certificate_replacement', 'independent_full_stack_restore', 'capacity_benchmark'}
    observation = record.get('observation', {})
    reasons = record.get('deferred_checks', {})
    if not isinstance(observation, dict) or not isinstance(reasons, dict):
        raise ValueError('Invalid stable observation or deferral record')
    if (record.get('version') != tag[1:]
            or record.get('decision') != 'accepted_with_documented_limitations'
            or record.get('owner_accepted_limitations') is not True
            or record.get('network_reachability_guarantee') is not False
            or record.get('advertised_client_capacity') is not False
            or set(reasons) != deferred
            or any(not isinstance(reason, str) or not reason.strip()
                   for reason in reasons.values())
            or observation.get('status') != 'complete'
            or observation.get('local_health_failures') != 0
            or observation.get('collection_errors') != 0
            or type(observation.get('samples')) is not int
            or observation['samples'] <= 0
            or record.get('local_restore') != 'PASS'
            or record.get('acme_staging_dry_run') != 'PASS'):
        raise ValueError('Stable requires the recorded owner decision and explicit verification limits')


def checked_manifest(folder):
    seen = set()
    for line in (folder / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if Path(name).name != name or name in seen or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Unsafe or duplicate checksum entry')
        seen.add(name)
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Release checksum mismatch')
    if not seen:
        raise ValueError('Empty checksum manifest')
    return seen


def verify_uploaded_asset(path, uploaded):
    # GitHub normalizes some special characters (including Debian's tilde).
    # A content digest alone cannot detect a broken download/checksum filename.
    if uploaded['name'] != path.name:
        raise ValueError('GitHub changed an asset filename; refusing publication')
    if uploaded['size'] != path.stat().st_size or uploaded['state'] != 'uploaded':
        raise ValueError('Release asset upload verification failed')
    digest = uploaded.get('digest')
    if digest and digest != 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError('GitHub asset digest mismatch')


def validate_upgrade_report(report, commit, package_sha256, baseline):
    old_packages = [name for name in baseline['assets_sha256'] if name.endswith('.deb')]
    if (len(old_packages) != 1 or report.get('status') != 'PASS'
            or report.get('candidate_commit') != commit
            or report.get('candidate_package_sha256') != package_sha256
            or report.get('baseline_commit') != baseline['commit']
            or report.get('baseline_version') != baseline['version']
            or report.get('baseline_package_sha256') != baseline['assets_sha256'][old_packages[0]]):
        raise ValueError('Published baseline upgrade evidence differs from this baseline or release candidate')


def withdraw_superseded(api):
    for entry in json.loads((ROOT / 'docs/releases/withdrawn.json').read_text()):
        release = api('GET','/releases/tags/'+entry['tag'])
        if not release:
            continue
        if release['target_commitish'] != entry['source_commit'] or not release['prerelease']:
            raise ValueError('Withdrawn release identity mismatch')
        body = entry['reason']+'\n\nUse '+entry['replacement_url']+' instead.\n'
        updates = {'name':'Withdrawn — '+entry['tag'], 'body':body, 'prerelease':True}
        if not release.get('immutable', False):
            updates['draft'] = True
        api('PATCH',f'/releases/{release["id"]}',updates)
        print('Superseded alpha marked withdrawn:',entry['tag'])


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_EVENT_NAME') != 'push':
        raise SystemExit('Publishing requires a successful GitHub tag push workflow')
    repo = os.environ['GITHUB_REPOSITORY']
    if repo != 'precox/SolarTT-UI' or os.environ.get('GITHUB_REF_TYPE') != 'tag':
        raise SystemExit('Unexpected repository or ref')
    tag = os.environ['GITHUB_REF_NAME']
    commit = subprocess.check_output(['git','rev-parse','HEAD'], text=True, cwd=ROOT).strip()
    if commit != os.environ['GITHUB_SHA']:
        raise SystemExit('Checkout differs from workflow source')
    subprocess.run(['git','fetch','--no-tags','origin','main'], cwd=ROOT, check=True)
    subprocess.run(['git','merge-base','--is-ancestor',commit,'FETCH_HEAD'], cwd=ROOT, check=True)
    version = tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['package']['version']
    inputs = ROOT / 'dist/release-input'
    metadata = json.loads((inputs / 'build.json').read_text())
    validate_identity(tag,commit,metadata,version)
    prerelease = release_is_prerelease(tag)
    acceptance = None
    if not prerelease:
        acceptance = json.loads((ROOT / 'docs/releases' / (tag + '-acceptance.json')).read_text())
        validate_stable_acceptance(tag, acceptance)
    original = checked_manifest(inputs)
    names = {f'solartt-ui_{version}_amd64.deb',
             f'solartt-ui-{version}-linux-x86_64.tar.gz',f'solartt-ui-{version}-source.tar.gz','build.json'}
    if original != names:
        raise SystemExit('Unexpected native artifact manifest')
    expected_jobs = {'security','portable','native','legacy','pilot','minimal'}
    results = json.loads(os.environ['RELEASE_JOB_RESULTS'])
    if set(results) != expected_jobs or any(v['result'] != 'success' for v in results.values()):
        raise SystemExit('Not every release prerequisite succeeded')
    output = ROOT / 'dist/publish'
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit('Release staging must be empty')
    for name in names | {'runtime-dependencies.json','license-review-result.json','measurements.txt','proxy-regression.json'}:
        shutil.copyfile(inputs / name, output / name)
    shutil.copyfile(ROOT / 'dist/minimal/minimal-runtime.json', output / 'minimal-runtime.json')
    shutil.copyfile(ROOT / 'dist/pilot/pilot-report.json', output / 'pilot-report.json')
    package_sha256 = hashlib.sha256((inputs / f'solartt-ui_{version}_amd64.deb').read_bytes()).hexdigest()
    for baseline in ['alpha5', 'alpha6', 'stable']:
        report_name = baseline + '-upgrade-report.json'
        report_path = ROOT / 'dist' / baseline / report_name
        validate_upgrade_report(json.loads(report_path.read_text()), commit, package_sha256,
                                json.loads((ROOT / 'upstream' / ('upgrade-' + baseline + '-pin.json')).read_text()))
        shutil.copyfile(report_path, output / report_name)
    if acceptance is not None:
        (output / 'release-acceptance.json').write_text(json.dumps(acceptance, indent=2) + '\n')
    for name in ['minimal-runtime.json','license-review-result.json']:
        if json.loads((output / name).read_text())['status'] != 'PASS':
            raise SystemExit('An attached release report did not pass')
    notes = (ROOT / 'docs/releases' / (tag + '.md')).read_text()
    (output / 'release-notes.md').write_text(notes)
    (output / 'release-tests.json').write_text(json.dumps({'source_commit':commit,
        'workflow_url':f'https://github.com/{repo}/actions/runs/{os.environ["GITHUB_RUN_ID"]}',
        'jobs':{name:results[name]['result'] for name in sorted(results)},
        'release_channel':'alpha' if prerelease else 'stable',
        'scope':'Isolated CI acceptance; verification limits and owner decision are recorded separately'},indent=2)+'\n')
    files = sorted(output.iterdir())
    (output / 'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in files))
    checked_manifest(output)
    token = os.environ['GH_TOKEN']
    api_root = f'https://api.github.com/repos/{repo}'
    def api(method,path,payload=None,content_type='application/json'):
        data = json.dumps(payload).encode() if isinstance(payload,dict) else payload
        url = path if path.startswith('https://uploads.github.com/') else api_root + path
        request = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
            'X-GitHub-Api-Version':'2022-11-28','Content-Type':content_type})
        try:
            with urllib.request.urlopen(request,timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if method == 'GET' and error.code == 404:
                return None
            raise RuntimeError(f'GitHub {method} failed: HTTP {error.code}') from None
    reporting = api('GET','/private-vulnerability-reporting')
    if not reporting or not reporting.get('enabled'):
        raise SystemExit('Private vulnerability reporting must be enabled before publication')
    existing = api('GET','/releases/tags/'+urllib.parse.quote(tag,safe=''))
    if existing and (existing['target_commitish'] != commit or existing['prerelease'] != prerelease):
        raise SystemExit('Existing release identity/type differs; refusing overwrite')
    # Resume only byte-identical assets in an interrupted draft. Published assets
    # are never replaced, and unexpected files require operator investigation.
    release = existing or api('POST','/releases',{'tag_name':tag,'target_commitish':commit,'name':'SolarTT-UI '+tag,
        'body':notes,'draft':True,'prerelease':prerelease,'make_latest':'false' if prerelease else 'true'})
    present = {asset['name']:asset for asset in release.get('assets',[])}
    if len(present) != len(release.get('assets',[])) or present.keys() - {p.name for p in output.iterdir()}:
        raise SystemExit('Unexpected or duplicate existing release assets')
    for path in sorted(output.iterdir()):
        if not re.fullmatch(r'[A-Za-z0-9._-]+',path.name):
            raise ValueError('Unsafe public asset filename')
        if path.name in present:
            asset = present[path.name]
            if (asset['size'] != path.stat().st_size or asset.get('digest') != 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()):
                raise SystemExit('Existing release asset differs; refusing overwrite')
            continue
        if not release['draft']:
            raise SystemExit('Published release is incomplete; refusing mutation')
        upload_url = release['upload_url'].split('{',1)[0]+'?name='+urllib.parse.quote(path.name,safe='')
        uploaded = api('POST',upload_url,path.read_bytes(),'application/octet-stream')
        verify_uploaded_asset(path,uploaded)
    published = (api('PATCH',f'/releases/{release["id"]}',{'draft':False,'prerelease':prerelease,'make_latest':'false' if prerelease else 'true'})
                 if release['draft'] else release)
    if published['draft'] or published['prerelease'] != prerelease:
        raise SystemExit('Unexpected published release state')
    withdraw_superseded(api)
    print('Published', 'alpha prerelease:' if prerelease else 'stable release:', published['html_url'])


if __name__ == '__main__':
    main()
