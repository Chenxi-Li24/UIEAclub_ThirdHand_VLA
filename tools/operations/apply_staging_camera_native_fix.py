"""Install the verified C2g native-publisher authentication compatibility fix."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

ARCHIVE_SHA = 'cf0013639f4a681d53ebf2ce6dcffb1c9ee33df0b2bfde1f1943343a27ce2ae1'
MANIFEST_SHA = '4c9ff6ab5b4d051ef7746a84ad19a6aae3d2cb59f24469d086d362a0b42802f3'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    root = Path(Path('/var/backups/thirdhand/C2g-backup-path').read_text().strip())
    old = Path('/opt/thirdhand-stage/releases/bbb537fe91f3ce2a')
    new = Path('/opt/thirdhand-stage/releases/cf0013639f4a681d')
    assert Path('/opt/thirdhand-stage/current').resolve() == old
    archive = root / 'C2g-native-camera-release.tar.gz'
    assert sha(archive) == ARCHIVE_SHA
    assert not new.exists()
    new.mkdir(mode=0o755)
    with tarfile.open(archive, 'r:gz') as tar:
        for item in tar:
            p = PurePosixPath(item.name)
            assert item.isfile() and not p.is_absolute() and '..' not in p.parts and p.parts[0] == 'thirdhand-stage'
            target = new.joinpath(*p.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(item) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o644)
    for name, _, _ in os.walk(new):
        Path(name).chmod(0o755)
    assert sha(new / 'manifest.json') == MANIFEST_SHA
    manifest = json.loads((new / 'manifest.json').read_text())['files']
    previous = json.loads((old / 'manifest.json').read_text())['files']
    assert len(manifest) == 4613 and set(manifest) == set(previous)
    assert [name for name in manifest if manifest[name] != previous[name]] == ['services/cloud-api/src/routes/media.js']
    assert {str(p.relative_to(new)) for p in new.rglob('*') if p.is_file()} == set(manifest) | {'manifest.json'}
    assert all(sha(new / name) == digest for name, digest in manifest.items())
    fragment = Path('/etc/thirdhand-stage/media-locations.inc')
    original = fragment.read_bytes()
    assert sha(fragment) == json.loads((root / 'ops-manifest.json').read_text())['media/media-locations.inc']
    (root / 'media-locations.before-native.inc').write_bytes(original)
    old_line = '    proxy_set_header X-Original-Sec-Fetch-Site $http_sec_fetch_site;\n'
    assert original.decode().count(old_line) == 1
    fragment.write_text(original.decode().replace(old_line, old_line + '    proxy_set_header X-Original-Authorization $http_authorization;\n'))
    subprocess.run(['/usr/sbin/nginx', '-t'], check=True, capture_output=True)
    link = Path('/opt/thirdhand-stage/current.C2g-native')
    assert not link.exists()
    link.symlink_to(new)
    link.replace('/opt/thirdhand-stage/current')
    subprocess.run(['systemctl', 'restart', 'thirdhand-stage.service'], check=True)
    subprocess.run(['systemctl', 'reload', 'nginx.service'], check=True)
    result = {'success': True, 'oldRelease': str(old), 'newRelease': str(new), 'verifiedFiles': len(manifest),
              'archiveSha256': ARCHIVE_SHA, 'manifestSha256': MANIFEST_SHA, 'newPorts': [], 'deviceControl': False}
    (root / 'native-auth-fix.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
