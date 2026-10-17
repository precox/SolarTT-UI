#!/usr/bin/env python3
"""Runtime-only Ubuntu container fixture; never run against an operator host."""
import hashlib
import http.server
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DOC = Path('/usr/share/doc/solartt-ui')


def run(*args, input=None):
    result = subprocess.run(args, input=input, capture_output=True)
    if result.returncode:
        raise RuntimeError('Runtime fixture command failed: ' + args[0])
    return result.stdout.decode()


def main():
    if (not Path('/.dockerenv').is_file() or os.geteuid() != 0
            or Path.cwd() != Path('/opt/solartt-test')
            or not Path('/opt/solartt-test/DISPOSABLE').is_file()):
        raise SystemExit('Only the disposable minimal-runtime CI container is supported')
    os.umask(0o077)
    os_release = Path('/etc/os-release').read_text()
    assert 'VERSION_ID="24.04"' in os_release and 'ID=ubuntu' in os_release
    absent = ['cargo', 'rustc', 'cc', 'gcc', 'g++', 'cmake', 'clang', 'node', 'chromium']
    assert all(shutil.which(name) is None for name in absent), 'Runtime image contains build tools'
    versions = {name: run(name, '--version').strip() for name in ('solartt-agent', 'solartt-panel', 'solartt-admin')}
    assert len({s.split()[-1] for s in versions.values()}) == 1
    assert not Path('/run/systemd/system').exists(), 'Container fixture must not claim host systemd coverage'
    account = __import__('pwd').getpwnam('solartt-panel')
    config = Path('/etc/solartt')
    for name in ['agent.toml', 'endpoint.toml', 'hosts.toml', 'panel.toml']:
        text = (DOC / 'examples' / name).read_text()
        if name == 'agent.toml':
            text = text.replace('allowed_uids = [1001]', f'allowed_uids = [{account.pw_uid}]')
        if name == 'panel.toml':
            assert '127.0.0.1:18081' in text and 'http://127.0.0.1:18081' in text
        path = config / name
        path.write_text(text)
        run('chown', 'root:solartt-control', str(path))
        path.chmod(0o640)
    run('install', '-d', '-o', 'solartt-agent', '-g', 'solartt-control', '-m', '0750', '/run/solartt')
    agent = ['runuser', '-u', 'solartt-agent', '-g', 'solartt-control', '-G', 'solartt-agent', '--']
    panel = ['runuser', '-u', 'solartt-panel', '-g', 'solartt-panel', '-G', 'solartt-control', '--']
    run(*agent, 'solartt-admin', 'init-key', '/var/lib/solartt/encryption.key')
    password = 'synthetic-minimal-runtime-only-password'
    run(*panel, 'solartt-panel', '--init-admin', '/var/lib/solartt-panel/admin.hash', input=password.encode())
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=media.example.org', '-addext', 'subjectAltName=DNS:media.example.org',
        '-keyout', '/etc/solartt/tls/private.key', '-out', '/etc/solartt/tls/fullchain.pem')
    for path in (config / 'tls').iterdir():
        run('chown', 'root:solartt-agent', str(path))
        path.chmod(0o640)
    class Cover(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'Minimal runtime cover fixture'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_):
            pass
    cover = http.server.ThreadingHTTPServer(('127.0.0.1', 9080), Cover)
    threading.Thread(target=cover.serve_forever, daemon=True).start()
    processes = []
    with tempfile.TemporaryFile() as logs:
        try:
            for cmd in (agent + ['solartt-agent', '/etc/solartt/agent.toml'], panel + ['solartt-panel', '/etc/solartt/panel.toml']):
                processes.append(subprocess.Popen(cmd, stdout=logs, stderr=logs))
            cookie = csrf = ''
            def api(path, payload):
                nonlocal cookie, csrf
                request = urllib.request.Request('http://127.0.0.1:18081' + path,
                    data=json.dumps(payload).encode(), headers={'Content-Type':'application/json',
                    'Origin':'http://127.0.0.1:18081', 'Cookie':cookie, 'X-CSRF-Token':csrf})
                with urllib.request.urlopen(request, timeout=3) as response:
                    if response.headers.get('Set-Cookie'):
                        cookie = response.headers['Set-Cookie'].split(';', 1)[0]
                    return json.load(response)
            deadline = time.monotonic() + 30
            while True:
                try:
                    csrf = api('/api/login', {'username':'admin', 'password':password})['csrf']
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() > deadline or any(p.poll() is not None for p in processes):
                        raise RuntimeError('Minimal panel failed to start') from None
                    time.sleep(.1)
            revision = None
            def command(op):
                nonlocal revision
                reply = api('/api/command', {'request_id':f'minimal-{time.time_ns()}', 'expected_revision':revision, 'command':op})
                revision = reply['desired_revision']
                assert reply['result']['kind'] != 'error'
                return reply['result']
            while True:
                try:
                    assert command({'op':'info'})['info']['readiness']
                    break
                except urllib.error.HTTPError as error:
                    if error.code != 503 or time.monotonic() > deadline:
                        raise
                    time.sleep(.1)
            assert not command({'op':'users', 'after':None})['users']
            user = command({'op':'create_user', 'label':'Synthetic minimal runtime', 'policy':{'limit_bytes':10000, 'expires_at':None, 'reset_monthly':False, 'device_limit':1}})['resource_id']
            credential = command({'op':'create_credential','user_id':user,'label':'Fixture'})['resource_id']
            exported = command({'op':'export_profile','credential_id':credential})
            assert exported['manual']['upstream_protocol'] == 'http2'
            assert exported['manual']['has_ipv6'] is False
            exported = None
            context = ssl.create_default_context(cafile='/etc/solartt/tls/fullchain.pem')
            context.set_alpn_protocols(['h2'])
            with socket.create_connection(('127.0.0.1',9443), timeout=3) as tcp:
                with context.wrap_socket(tcp,server_hostname='media.example.org') as tls:
                    assert tls.selected_alpn_protocol() == 'h2'
            denied = subprocess.run(panel + ['test','-r','/var/lib/solartt/encryption.key'], capture_output=True)
            assert denied.returncode != 0
            run(*agent, 'solartt-admin', 'backup', '/var/lib/solartt/policy.sqlite', '/var/lib/solartt/snapshot.sqlite')
            run(*agent, 'solartt-admin', 'check', '/var/lib/solartt/snapshot.sqlite', '/var/lib/solartt/encryption.key', 'UTC')
            rss = {}
            # Measure the actual ELF child, not the runuser supervisor.
            for label, proc in zip(('agent','panel'), processes):
                children = Path(f'/proc/{proc.pid}/task/{proc.pid}/children').read_text().split()
                assert len(children) == 1
                status = Path(f'/proc/{children[0]}/status').read_text().splitlines()
                rss[label] = int(next(line.split()[1] for line in status if line.startswith('VmRSS:')))
            result = {'status':'PASS', 'os':'Ubuntu 24.04 x86_64', 'environment':'minimal Docker runtime, not systemd PID 1',
                'versions':versions, 'absent_tools':absent, 'installed_size_kib':int(run('dpkg-query','-W','-f=${Installed-Size}','solartt-ui')),
                'installed_payload_bytes':sum(p.stat().st_size for p in list(Path('/usr/bin').glob('solartt-*')) + list(DOC.rglob('*')) if p.is_file()),
                'sampled_rss_kib':rss, 'checks':['declared_runtime_dependencies','packaged_configuration','dedicated_accounts','admin_login','unix_control_readiness','profile_limit_and_manual_export','verified_tls_h2','panel_key_denial','backup_check'],
                'scope':'Process/runtime acceptance; systemd install/upgrade/removal is tested separately on a GitHub VM. No sustained capacity or Android claim.'}
            Path('/report/minimal-runtime.json').write_text(json.dumps(result,indent=2)+'\n')
            print('Minimal Ubuntu runtime: PASS; no compiler, Rust, Node or Chromium installed')
        finally:
            for proc in reversed(processes):
                proc.terminate()
            for proc in reversed(processes):
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=3)
            cover.shutdown()


if __name__ == '__main__':
    main()
