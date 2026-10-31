"""Apply only the tested workspace-startup fix; preserve identity/media policy."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import time
import urllib.request

ARCHIVE_SHA = 'fecd12218feca5740f6d4297f94576141c3057ef939ac864ee7d6448aced0c6f'
MANIFEST_SHA = 'a6f9ad9db12fcade0eb206f59df1de139fa7c7ef66f3d92105186cf520584adb'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    root = Path(Path('/var/backups/thirdhand/C2g-backup-path').read_text().strip())
    backup = Path('/var/backups/thirdhand/access-C2h-workspace-20261031')
    old = Path('/opt/thirdhand-stage/releases/cf0013639f4a681d')
    new = Path('/opt/thirdhand-stage/releases/fecd12218feca574')
    current = Path('/opt/thirdhand-stage/current')
    assert current.resolve() == old and not backup.exists() and not new.exists()
    archive = root / 'C2h-workspace-ready-release.tar.gz'
    assert sha(archive) == ARCHIVE_SHA
    environment = Path('/etc/thirdhand-stage/cloud.env')
    showcase = Path('/www/wwwroot/uiea-thirdhand-static/index.html')
    env_sha, showcase_sha = sha(environment), sha(showcase)
    backup.mkdir(mode=0o700)
    (backup / 'previous-release.txt').write_text(str(old))
    new.mkdir(mode=0o755)
    with tarfile.open(archive, 'r:gz') as tar:
        for item in tar:
            parts = PurePosixPath(item.name)
            assert item.isfile() and not parts.is_absolute() and '..' not in parts.parts
            assert parts.parts[0] == 'thirdhand-stage' and len(parts.parts) > 1
            target = new.joinpath(*parts.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(item) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o644)
    for directory, _, _ in os.walk(new):
        Path(directory).chmod(0o755)
    assert sha(new / 'manifest.json') == MANIFEST_SHA
    manifest = json.loads((new / 'manifest.json').read_text())['files']
    previous = json.loads((old / 'manifest.json').read_text())['files']
    assert len(manifest) == 4613 and set(manifest) == set(previous)
    assert [name for name in manifest if manifest[name] != previous[name]] == ['apps/web/public/js/cloud-workspace.js']
    assert {str(p.relative_to(new)) for p in new.rglob('*') if p.is_file()} == set(manifest) | {'manifest.json'}
    assert all(sha(new / name) == digest for name, digest in manifest.items())
    link = Path('/opt/thirdhand-stage/current.C2h')
    assert not link.exists()
    link.symlink_to(new)
    link.replace(current)
    try:
        subprocess.run(['systemctl', 'restart', 'thirdhand-stage.service'], check=True)
        for attempt in range(20):
            try:
                with urllib.request.urlopen('http://127.0.0.1:3202/healthz', timeout=2) as response:
                    health = json.load(response)
                assert health['deviceControl'] == 'unavailable'
                break
            except Exception:
                if attempt == 19:
                    raise
                time.sleep(0.25)
        assert sha(environment) == env_sha and sha(showcase) == showcase_sha
    except Exception:
        rollback = Path('/opt/thirdhand-stage/current.C2h-rollback')
        assert not rollback.exists()
        rollback.symlink_to(old)
        rollback.replace(current)
        subprocess.run(['systemctl', 'restart', 'thirdhand-stage.service'], check=True)
        raise
    result = {'success': True, 'oldRelease': str(old), 'newRelease': str(new), 'verifiedFiles': len(manifest),
              'archiveSha256': ARCHIVE_SHA, 'manifestSha256': MANIFEST_SHA,
              'onlyChangedFile': 'apps/web/public/js/cloud-workspace.js', 'environmentUnchanged': True,
              'showcaseSha256': showcase_sha, 'newPorts': [], 'deviceControl': False}
    (backup / 'acceptance.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
