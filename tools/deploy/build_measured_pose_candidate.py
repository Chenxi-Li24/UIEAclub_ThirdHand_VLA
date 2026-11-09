"""Offline fixed four-file cloud UI candidate; does not connect to any service."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[2]
BASE_SHA = 'a287e6b5558f02b5604263d0abba464831ff8df9faff4999fb43e840e3132edd'
FILES = tuple('apps/web/public/js/' + name + '.js' for name in (
    'robot-viewer', 'i18n-cloud-catalog',
    'simulation-controller', 'workspace-session'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pretty(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def build(baseline, source, destination):
    raw = baseline.read_bytes()
    if sha(raw) != BASE_SHA:
        raise ValueError('Cloud baseline changed')
    before = json.loads(raw)
    if len(before['files']) != 4658:
        raise ValueError('Inventory changed')
    source = subprocess.check_output(['git', 'rev-parse', '--verify', source + '^{commit}'], cwd=REPO, text=True).strip()
    changes = {}
    for name in FILES:
        previous = subprocess.check_output(['git', 'show', source + '^:' + name], cwd=REPO)
        if sha(previous) != before['files'].get(name):
            raise ValueError('Installed source differs from parent: ' + name)
        changes[name] = subprocess.check_output(['git', 'show', source + ':' + name], cwd=REPO)
    after = {**before['files'], **{name: sha(data) for name, data in changes.items()}}
    if {name for name in after if before['files'].get(name) != after[name]} != set(FILES):
        raise ValueError('Unexpected changed set')
    manifest = pretty({**before, 'files': after})
    cloud = dict(before=before['files'], after=after,
                 changes={name: base64.b64encode(data).decode() for name, data in changes.items()},
                 oldRelease='/opt/thirdhand-stage/releases/' + BASE_SHA[:16], oldManifestSha256=BASE_SHA,
                 newRelease='/opt/thirdhand-stage/releases/' + sha(manifest)[:16], newManifestSha256=sha(manifest),
                 manifestBase64=base64.b64encode(manifest).decode())
    packed = gzip.compress(pretty(dict(schema=1, purpose='measured-pose-fix', sourceCommit=source, cloud=cloud)), mtime=0)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'measured-pose-candidate.json.gz').write_bytes(packed)
    (destination / 'cloud-manifest.json').write_bytes(manifest)
    report = dict(sourceCommit=source, packageSha256=sha(packed), packageBytes=len(packed),
                  newRelease=cloud['newRelease'], manifestSha256=sha(manifest),
                  changes={name: after[name] for name in FILES}, preserved=4654)
    (destination / 'summary.json').write_bytes(pretty(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.baseline, args.source, args.destination), indent=2))
