"""C5: tested history/member display fix; no SDK or authorization changes."""
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

ROOT = Path('/var/backups/thirdhand/access-C5-history-display-20261031')
OLD = Path('/opt/thirdhand-stage/releases/4e858d8b13b8ea6b')
CURRENT = Path('/opt/thirdhand-stage/current')
EXPECTED = {
    'apps/web/public/history.html', 'apps/web/public/css/history.css',
    'apps/web/public/js/account-security.js', 'apps/web/public/js/history-dates.js',
    'apps/web/public/js/history-page.js', 'apps/web/public/js/i18n-cloud-catalog.js',
    'apps/web/public/js/i18n-history-catalog.js', 'services/cloud-api/src/workspace-pages.js',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def switch(target):
    temporary = CURRENT.with_name('current.C5-history')
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


def main(apply):
    os.umask(0o077)
    assert os.geteuid() == 0 and CURRENT.resolve() == OLD
    package = json.loads(gzip.decompress((ROOT / 'C5-history-display.delta.json.gz').read_bytes()))
    new = OLD.with_name(package['archiveSha256'][:16])
    assert not new.exists()
    old_manifest = (OLD / 'manifest.json').read_bytes()
    assert sha(old_manifest) == package['oldManifestSha256']
    previous = json.loads(old_manifest)['files']
    manifest = base64.b64decode(package['manifestBase64'], validate=True)
    assert sha(manifest) == package['manifestSha256']
    files = json.loads(manifest)['files']
    assert set(files) - set(previous) == {'apps/web/public/js/history-dates.js'}
    assert not set(previous) - set(files)
    assert {name for name in files if previous.get(name) != files[name]} == set(package['changes']) == EXPECTED
    assert all(sha((OLD / name).read_bytes()) == digest for name, digest in previous.items())
    contents = {name: base64.b64decode(value, validate=True) for name, value in package['changes'].items()}
    assert all(sha(data) == files[name] for name, data in contents.items())
    environment = Path('/etc/thirdhand-stage/cloud.env')
    env_sha = sha(environment.read_bytes())
    showcase = Path('/www/wwwroot/uiea-thirdhand-static/index.html')
    site_sha = sha(showcase.read_bytes())
    report = {'applied': False, 'oldRelease': str(OLD), 'newRelease': str(new),
              'changes': sorted(contents), 'authConfigurationUnchanged': True,
              'newPublicPorts': [], 'databaseMigrations': [], 'sdkActions': 0, 'motionCommands': 0}
    (ROOT / 'review.json').write_text(json.dumps(report, indent=2))
    if not apply:
        print(json.dumps(report))
        return
    (ROOT / 'before-release.txt').write_text(str(OLD))
    shutil.copytree(OLD, new)
    for name, data in contents.items():
        (new / name).write_bytes(data)
        (new / name).chmod(0o644)
    (new / 'manifest.json').write_bytes(manifest)
    assert all(sha((new / name).read_bytes()) == digest for name, digest in files.items())
    switched = False
    try:
        switch(new)
        switched = True
        subprocess.run(['systemctl', 'restart', 'thirdhand-stage.service'], check=True)
        health()
        assert sha(environment.read_bytes()) == env_sha
        assert sha(showcase.read_bytes()) == site_sha
    except Exception:
        if switched:
            switch(OLD)
            subprocess.run(['systemctl', 'restart', 'thirdhand-stage.service'], check=True)
        raise
    report['applied'] = True
    report['completedAtUnix'] = time.time()
    (ROOT / 'applied.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    main(parser.parse_args().apply)
