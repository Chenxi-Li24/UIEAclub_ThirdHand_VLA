"""Freeze only C2 business sources, authenticated assets and pinned dependencies."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile

REPO = Path(__file__).resolve().parents[2]
PLAN = REPO / '.superpowers/sdd/2026-10-30-public-access-rollout'


def contains_private_key(data):
    normalized = data.replace(b'\\r', b'\r').replace(b'\\n', b'\n')
    return re.search(rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----\s*[A-Za-z0-9+/=\s]{32,}-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----', normalized) is not None


def build():
    output = PLAN / 'C2-release'
    assert output.is_dir() and not output.is_symlink()
    for name in ('package.json', 'package-lock.json'):
        assert (output / name).read_bytes() == (REPO / 'deploy/public-access/staging' / name).read_bytes()
    lock = json.loads((output / 'package-lock.json').read_text())
    assert all(not item.get('link') and (not name or name.startswith('node_modules/'))
               for name, item in lock['packages'].items())
    assert all(not name or item.get('resolved', '').startswith('https://registry.npmjs.org/')
               and item.get('integrity', '').startswith(('sha512-', 'sha1-'))
               for name, item in lock['packages'].items())
    entries = ['services/cloud-api/src/staging-main.js', 'services/cloud-api/src/jobs/export-main.js',
               'platform/storage/src/migrate-cli.js', 'platform/identity/src/bootstrap-admin.js',
               'tools/operations/isolate_staging_restore.js']
    selected = set()
    pending = [REPO / name for name in entries]
    while pending:
        file = pending.pop().resolve()
        relative = file.relative_to(REPO).as_posix()
        if relative in selected:
            continue
        assert relative.startswith(('services/cloud-api/src/', 'services/device-relay/src/', 'platform/identity/src/', 'platform/storage/src/',
                                    'platform/contracts/', 'tools/operations/')) or relative in {
                                        'services/robot/src/control-policy.js', 'services/robot/src/lease-watchdog.js', 'services/robot/src/motion-policy.js', 'services/device-relay/src/protocol.js',
                                        'apps/web/public/js/tutorial-adapter.js'}, relative
        selected.add(relative)
        for dependency in re.findall(r"require\(['\"]([^'\"]+)['\"]\)", file.read_text(encoding='utf-8')):
            if not dependency.startswith('.'):
                continue
            target = file.parent / dependency
            options = [target, Path(str(target) + '.js'), Path(str(target) + '.json'), target / 'index.js']
            resolved = next((p for p in options if p.is_file()), None)
            if not resolved:
                raise ValueError('Unresolved relative dependency: ' + relative + ' -> ' + dependency)
            pending.append(resolved)
    selected.update(p.relative_to(REPO).as_posix() for p in (REPO / 'platform/storage/migrations').glob('*.sql'))
    workspace = (REPO / 'services/cloud-api/src/workspace-pages.js').read_text(encoding='utf-8')
    values = re.search(r'const files=new Set\(\[(.*?)\]\);', workspace, re.S).group(1)
    assets = set(re.findall(r"'([^']+)'", values))
    assets.update(['index.html', 'history.html', 'login.html', 'register.html', 'forgot-password.html',
                   'reset-password.html', 'verify-email.html', 'css/auth.css', 'js/i18n-catalog.js',
                   'js/i18n-auth-catalog.js', 'js/i18n.js', 'js/preferences.js', 'js/auth-page.js'])
    public = REPO / 'apps/web/public'
    selected.update((Path('apps/web/public') / name).as_posix() for name in assets if (public / name).is_file())
    for directory, names, leaves in os.walk(public / 'js/lib', followlinks=False):
        for name in names:
            child = Path(directory) / name
            assert not child.is_symlink() and not getattr(child, 'is_junction', lambda: False)()
        for name in leaves:
            file = Path(directory) / name
            if file.suffix in ('.js', '.mjs'):
                selected.add(file.relative_to(REPO).as_posix())
    selected.add('apps/web/public/js/lib/qrcode-generator-2.0.4.LICENSE.txt')
    selected.add('assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf')
    geometry = list((REPO / 'assets/robot/startouch-v3/meshes').glob('*.STL'))
    assert len(geometry) == 9
    selected.update(file.relative_to(REPO).as_posix() for file in geometry)
    for relative in selected:
        file = REPO / relative
        assert not file.is_symlink()
        assert not file.read_bytes()[:200].startswith(b'version https://git-lfs.github.com')
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, destination)
    hashes = {}
    for directory, names, leaves in os.walk(output, followlinks=False):
        names[:] = [name for name in names if name != '.bin']
        for name in names:
            child = Path(directory) / name
            assert not child.is_symlink() and not getattr(child, 'is_junction', lambda: False)()
        for name in leaves:
            file = Path(directory) / name
            relative = file.relative_to(output).as_posix()
            if relative == 'manifest.json':
                continue
            assert not file.is_symlink()
            if not relative.startswith('node_modules/'):
                assert relative in selected | {'package.json', 'package-lock.json'}, relative
            if file.suffix == '.node' and relative != 'node_modules/argon2/prebuilds/linux-x64/argon2.glibc.node':
                continue
            assert file.suffix not in ('.pem', '.key', '.sqlite', '.pyc', '.env')
            data = file.read_bytes()
            assert not contains_private_key(data), relative
            hashes[relative] = hashlib.sha256(data).hexdigest()
    manifest = {'format': 1, 'mode': 'staging-business-with-opt-in-sdk', 'node': '24.22.1',
                'deviceControl': 'explicit-read-only-enrollment', 'defaultDeviceControl': False,
                'hardwareIncluded': False, 'files': hashes}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    archive = PLAN / 'C2-staging-release.tar.gz'
    with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w') as tar:
            for relative in sorted([*hashes, 'manifest.json']):
                data = (output / relative).read_bytes()
                info = tarfile.TarInfo('thirdhand-stage/' + relative)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
    print(json.dumps({'path': str(archive), 'files': len(hashes), 'bytes': archive.stat().st_size,
                      'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    build()
