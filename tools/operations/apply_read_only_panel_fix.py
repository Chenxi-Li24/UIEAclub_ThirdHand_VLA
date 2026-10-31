"""Apply the tested C3a workspace visibility fix without changing authorization."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

OLD = Path('/opt/thirdhand-stage/releases/325d182fe15199d5')
NEW = Path('/opt/thirdhand-stage/releases/f2c14f11d88c289e')
CURRENT = Path('/opt/thirdhand-stage/current')
ROOT = Path('/var/backups/thirdhand/access-C3a-sdk-readonly-20261031')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def switch(target):
    temporary = Path('/opt/thirdhand-stage/current.C3a-panel')
    assert not temporary.exists(); temporary.symlink_to(target); temporary.replace(CURRENT)


def main():
    os.umask(0o077); assert os.geteuid() == 0 and CURRENT.resolve() == OLD and not NEW.exists()
    package = ROOT / 'C3a-visible-controls.delta.json.gz'
    value = json.loads(gzip.decompress(package.read_bytes()))
    assert value['archiveSha256'] == 'f2c14f11d88c289e53be824102e3acbef09666d9d338e5007007c49f2c8dd007'
    old = json.loads((OLD / 'manifest.json').read_text())['files']
    manifest = value['manifest']; new = manifest['files']
    assert set(old) == set(new)
    changed = sorted(name for name in old if old[name] != new[name])
    assert changed == ['apps/web/public/css/cloud-workspace.css', 'apps/web/public/js/admin-control.js']
    assert set(value['changes']) == set(changed)
    assert all(sha(OLD / name) == digest for name, digest in old.items())
    environment = Path('/etc/thirdhand-stage/cloud.env'); env_sha = sha(environment)
    contents = {}
    for name, text in value['changes'].items():
        data = text.encode('utf-8')
        if hashlib.sha256(data).hexdigest() != new[name]:
            data = text.replace('\n', '\r\n').encode('utf-8')
        assert hashlib.sha256(data).hexdigest() == new[name]
        contents[name] = data
    assert hashlib.sha256(value['manifestText'].encode('utf-8')).hexdigest() == value['manifestSha256']
    shutil.copytree(OLD, NEW)
    for name, data in contents.items():
        (NEW / name).write_bytes(data)
    (NEW / 'manifest.json').write_text(value['manifestText'])
    assert sha(NEW / 'manifest.json') == value['manifestSha256']
    assert all(sha(NEW / name) == digest for name, digest in new.items())
    try:
        switch(NEW); subprocess.run(['systemctl', 'restart', 'thirdhand-stage.service'], check=True)
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:3202/healthz', timeout=2) as response:
                    assert json.load(response)['deviceControl'] == 'explicit-read-only'
                break
            except Exception:
                if attempt == 29: raise
                time.sleep(0.25)
        assert sha(environment) == env_sha
    except Exception:
        switch(OLD); subprocess.run(['systemctl', 'restart', 'thirdhand-stage.service'], check=True); raise
    report = {'applied': True, 'release': str(NEW), 'changed': changed,
              'authorizationUnchanged': True, 'newPublicPorts': [], 'motionCommands': 0}
    (ROOT / 'panel-fix-applied.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
