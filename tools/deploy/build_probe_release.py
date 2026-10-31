"""Build a minimal reviewable probe release in this plan's ignored workspace.

Run after npm ci in OUTPUT using the isolated deploy/public-access/probe lock.
No credentials, robot runtime, hardware drivers or application service included.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile

REPO = Path(__file__).resolve().parents[2]
PLAN = REPO / '.superpowers/sdd/2026-10-30-public-access-rollout'
NODE_FILES = [f'services/device-relay/src/{name}.js'
              for name in ('probe-main', 'probe-config', 'probe-service', 'probe-enroll', 'server', 'protocol', 'registry')]
FILES = NODE_FILES + ['platform/storage/src/pool.js', 'tools/operations/reload_public_tls.py',
                     'deploy/public-access/nginx/edge-probe.conf.template']
FILES += [f'deploy/public-access/probe/{name}' for name in
          ('bootstrap.sql', 'postgresql.conf.fragment', 'pg_hba.conf.fragment', 'python-requirements.lock',
           'pki-ca.cnf', 'pki-client.ext.template')]
FILES += [f'deploy/public-access/systemd/{name}' for name in
          ('thirdhand-probe-relay.service.template', 'postgresql-probe-budget.conf.template',
           'thirdhand-public-tls.service.template', 'thirdhand-public-tls.path.template',
           'thirdhand-public-tls.timer.template')]
PYTHON_FILES = ('__init__.py', 'probe.py', 'probe_measurements.py', 'protocol.py', 'transport.py')


def build(output):
    output = output.resolve()
    if output.parent != PLAN.resolve() or output.name != 'C1b-release':
        raise ValueError('Release output must be this plan workspace/C1b-release')
    for name in ('package.json', 'package-lock.json'):
        source = REPO / 'deploy/public-access/probe' / name
        if (output / name).read_bytes() != source.read_bytes():
            raise ValueError('Install the exact isolated probe lock first')
    lock = json.loads((output / 'package-lock.json').read_text())
    if any(item.get('link') or name and not name.startswith('node_modules/')
           for name, item in lock['packages'].items()):
        raise ValueError('Linked or external package metadata rejected')
    for name, version in [('pg', '8.23.1'), ('ws', '8.21.3')]:
        if json.loads((output / 'node_modules' / name / 'package.json').read_text())['version'] != version:
            raise ValueError('Dependency version mismatch')
    for relative in FILES:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, destination)
    python = output / 'python-probe'
    (python / 'src/thirdhand_edge').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / 'deploy/public-access/probe/python-pyproject.toml', python / 'pyproject.toml')
    for name in PYTHON_FILES:
        shutil.copyfile(REPO / 'services/edge-agent/src/thirdhand_edge' / name, python / 'src/thirdhand_edge' / name)

    expected = set(FILES) | {'package.json', 'package-lock.json', 'python-probe/pyproject.toml'}
    expected |= {f'python-probe/src/thirdhand_edge/{name}' for name in PYTHON_FILES}
    contents = {}
    files = []
    for directory, names, leaves in os.walk(output, topdown=True, followlinks=False):
        for name in names:
            child = Path(directory) / name
            if child.is_symlink() or getattr(child, 'is_junction', lambda: False)():
                raise ValueError('Linked release directory rejected before traversal')
        files.extend(Path(directory) / name for name in leaves)
    for file in sorted(files):
        if not file.is_file() or file.name == 'manifest.json':
            continue
        relative = file.relative_to(output).as_posix()
        if file.is_symlink() or file.suffix in ('.node', '.pem', '.key', '.sqlite', '.pyc'):
            raise ValueError('Unexpected native, credential or runtime artifact')
        if not relative.startswith('node_modules/') and relative not in expected:
            raise ValueError('Unlisted release file')
        data = file.read_bytes()
        if b'-----BEGIN PRIVATE KEY-----' in data or b'-----BEGIN RSA PRIVATE KEY-----' in data:
            raise ValueError('Private key material rejected')
        contents[relative] = hashlib.sha256(data).hexdigest()
    manifest = {'format': 1, 'mode': 'probe-only', 'node': '24.22.1', 'postgresql': '17.11',
                'files': contents, 'hardwareIncluded': False, 'applicationIncluded': False}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    archive = PLAN / 'C1b-probe-release.tar.gz'
    names = sorted([*contents, 'manifest.json'])
    directories = {'thirdhand-probe'}
    for name in names:
        parent = Path('thirdhand-probe', name).parent
        while parent != Path('.'):
            directories.add(parent.as_posix())
            parent = parent.parent
    with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w') as tar:
            for name in sorted(directories):
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            for name in names:
                data = (output / name).read_bytes()
                info = tarfile.TarInfo('thirdhand-probe/' + name)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    print(json.dumps({'archive': str(archive), 'sha256': digest, 'files': len(contents), 'bytes': archive.stat().st_size}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
