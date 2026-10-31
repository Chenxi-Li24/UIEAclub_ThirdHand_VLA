"""Apply the reviewed static-entry and CSV-only business delta; no auth/config changes."""
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

ROOT = Path('/var/backups/thirdhand/access-C4-showcase-tables-20261031')
CURRENT = Path('/opt/thirdhand-stage/current')
SHOWCASE = Path('/www/wwwroot/uiea-thirdhand-static')
EXPECTED = {
    'apps/web/public/history.html',
    'apps/web/public/js/account-security.js',
    'apps/web/public/js/i18n-cloud-catalog.js',
    'services/cloud-api/src/jobs/export-worker.js',
    'services/cloud-api/src/routes/admin.js',
    'services/cloud-api/src/table-export.js',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def switch(target):
    temporary = CURRENT.with_name('current.C4-tables')
    assert not temporary.exists() and not temporary.is_symlink()
    temporary.symlink_to(target)
    temporary.replace(CURRENT)


def health():
    for attempt in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:3202/healthz', timeout=2) as response:
                assert json.load(response)['deviceControl'] == 'explicit-read-only'
            return
        except Exception:
            if attempt == 29:
                raise
            time.sleep(0.25)


def main(apply=False):
    os.umask(0o077)
    assert os.geteuid() == 0
    package = json.loads(gzip.decompress((ROOT / 'C4-showcase-tables.delta.json.gz').read_bytes()))
    old = Path('/opt/thirdhand-stage/releases/f2c14f11d88c289e')
    new = old.with_name(package['archiveSha256'][:16])
    assert CURRENT.resolve() == old and not new.exists()
    old_manifest_bytes = (old / 'manifest.json').read_bytes()
    assert sha(old_manifest_bytes) == package['oldManifestSha256']
    old_files = json.loads(old_manifest_bytes)['files']
    manifest_bytes = base64.b64decode(package['manifestBase64'], validate=True)
    assert sha(manifest_bytes) == package['manifestSha256']
    files = json.loads(manifest_bytes)['files']
    assert set(files) - set(old_files) == {'services/cloud-api/src/table-export.js'}
    assert not set(old_files) - set(files)
    changed = {name for name in files if old_files.get(name) != files[name]}
    assert changed == set(package['changes']) == EXPECTED
    for name, digest in old_files.items():
        assert sha((old / name).read_bytes()) == digest, name
    contents = {name: base64.b64decode(package['changes'][name], validate=True) for name in changed}
    assert all(sha(data) == files[name] for name, data in contents.items())
    assert SHOWCASE.resolve() == SHOWCASE and not (SHOWCASE / 'index.html').is_symlink()
    site = package['showcase']
    old_index = (SHOWCASE / 'index.html').read_bytes()
    assert sha(old_index) == site['oldIndexSha256']
    assert sha((SHOWCASE / site['oldJsPath']).read_bytes()) == site['oldJsSha256']
    assert sha((SHOWCASE / site['cssPath']).read_bytes()) == site['cssSha256']
    index = base64.b64decode(site['indexBase64'], validate=True)
    javascript = base64.b64decode(site['jsBase64'], validate=True)
    assert sha(index) == site['indexSha256'] and sha(javascript) == site['jsSha256']
    target = SHOWCASE / site['jsPath']
    assert target.parent.resolve() == SHOWCASE / 'assets' and target.suffix == '.js'
    assert ('/' + site['jsPath']).encode() in index
    assert b'https://staging.uiea-thirdhand.com/login' in javascript
    assert not target.exists() or sha(target.read_bytes()) == site['jsSha256']
    environment = Path('/etc/thirdhand-stage/cloud.env')
    env_sha = sha(environment.read_bytes())
    query = subprocess.check_output(['/usr/sbin/runuser', '-u', 'postgres', '--', '/usr/lib/postgresql/17/bin/psql', '-X', '-q', '-At', '-h', '/run/thirdhand-stage-db', '-p', '55440', '-d', 'thirdhand_stage', '-c', "SELECT COUNT(*) FROM ops.export_jobs WHERE status='running'"], text=True)
    assert query.strip() == '0', 'An export is running; retry after it completes'
    report = {'applied': False, 'oldRelease': str(old), 'newRelease': str(new),
              'businessChanges': sorted(changed), 'showcaseChanges': ['index.html', site['jsPath']],
              'databaseMigrations': [], 'newPublicPorts': [], 'authConfigurationUnchanged': True,
              'sdkActions': 0, 'motionCommands': 0}
    (ROOT / 'review.json').write_text(json.dumps(report, indent=2))
    if not apply:
        print(json.dumps(report))
        return
    before = ROOT / 'before'
    before.mkdir(mode=0o700)
    (before / 'showcase-index.html').write_bytes(old_index)
    (before / 'active-release.txt').write_text(str(old))
    shutil.copytree(old, new)
    for name, data in contents.items():
        (new / name).write_bytes(data)
        (new / name).chmod(0o644)
    (new / 'manifest.json').write_bytes(manifest_bytes)
    assert all(sha((new / name).read_bytes()) == digest for name, digest in files.items())
    switched = site_switched = False
    try:
        switch(new)
        switched = True
        for service in ['thirdhand-stage.service', 'thirdhand-stage-export.service']:
            subprocess.run(['systemctl', 'restart', service], check=True)
        health()
        if not target.exists():
            with target.open('xb') as output:
                output.write(javascript)
            target.chmod(0o644)
        temporary = SHOWCASE / 'index.C4-tables.tmp'
        with temporary.open('xb') as output:
            output.write(index)
        temporary.chmod(0o644)
        temporary.replace(SHOWCASE / 'index.html')
        site_switched = True
        assert sha(environment.read_bytes()) == env_sha
        assert sha((SHOWCASE / 'index.html').read_bytes()) == site['indexSha256']
    except Exception:
        errors = []
        if site_switched:
            try:
                (SHOWCASE / 'index.html').write_bytes(old_index)
            except Exception as error:
                errors.append({'step': 'showcase', 'type': type(error).__name__})
        if switched:
            try:
                switch(old)
            except Exception as error:
                errors.append({'step': 'release', 'type': type(error).__name__})
            for service in ['thirdhand-stage.service', 'thirdhand-stage-export.service']:
                try:
                    subprocess.run(['systemctl', 'restart', service], check=True)
                except Exception as error:
                    errors.append({'step': service, 'type': type(error).__name__})
        (ROOT / 'rollback.json').write_text(json.dumps({'errors': errors}))
        raise
    report['applied'] = True
    report['completedAtUnix'] = time.time()
    (ROOT / 'applied.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    main(parser.parse_args().apply)
