"""Build the SDK scope and latest-state cloud delta from a fixed Git commit, never a dirty worktree.

Ubuntu and Nginx are deliberately separate: their installed baselines must be
reviewed before a device-side deployment candidate is approved.
"""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[2]
SOURCE = '3512410788da5e4e2878137e4ddd7e172e5bcdd4'
OLD_SHA = 'dfbca02d47ca7f4020354567482265c5f2645a76e509a3f82cf4d23641d5aa4e'
OLD = '/opt/thirdhand-stage/releases/' + OLD_SHA[:16]
CHANGED = {'apps/web/public/js/' + n + '.js' for n in ('admin-control', 'device-state', 'i18n-cloud-catalog')} | {
    'platform/identity/src/policy.js', 'platform/storage/src/leases.js',
    'services/cloud-api/src/control/control-channel.js', 'services/cloud-api/src/control/leases.js',
    'services/cloud-api/src/control/websocket.js', 'services/cloud-api/src/routes/control.js',
    'services/device-relay/src/server.js'}
MIGRATION = '012-sdk-connection-scope.sql'
ADDED = {'platform/storage/migrations/' + MIGRATION}
FILES = CHANGED | ADDED


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_bytes(name):
    return subprocess.run(['git', 'show', SOURCE + ':' + name], cwd=REPO,
                          capture_output=True, check=True).stdout


def build(baseline, destination, read_source=source_bytes):
    raw = baseline.read_bytes()
    if sha(raw) != OLD_SHA:
        raise ValueError('C8 baseline manifest changed')
    before = json.loads(raw)
    if len(before['files']) != 4656 or not FILES - ADDED <= before['files'].keys() or ADDED & before['files'].keys():
        raise ValueError('Baseline inventory changed')
    contents = {name: read_source(name) for name in sorted(FILES)}
    after = json.loads(raw)
    after['files'].update({name: sha(data) for name, data in contents.items()})
    changed = {name for name in after['files'] if before['files'].get(name) != after['files'][name]}
    if changed != FILES:
        raise ValueError('Candidate has an unchanged or extra source')
    manifest = (json.dumps(after, sort_keys=True, indent=2) + '\n').encode()
    digest = sha(manifest)
    package = {'format': 1, 'oldRelease': OLD,
               'newRelease': '/opt/thirdhand-stage/releases/' + digest[:16],
               'oldManifestSha256': OLD_SHA, 'manifestSha256': digest,
               'beforeHashes': {n: before['files'].get(n) for n in sorted(FILES)},
               'manifestBase64': base64.b64encode(manifest).decode(),
               'changes': {n: base64.b64encode(v).decode() for n, v in contents.items()}}
    packed = gzip.compress(json.dumps(package, sort_keys=True, separators=(',', ':')).encode(), mtime=0)
    report = {k: v for k, v in package.items() if k not in ('changes', 'manifestBase64', 'beforeHashes')}
    report.update(sourceCommit=SOURCE, sourcePins={n: sha(v) for n, v in contents.items()},
                  packageSha256=sha(packed), packageBytes=len(packed), filesCount=len(after['files']),
                  preservedFiles=len(before['files']) - len(FILES - ADDED), addedFiles=sorted(ADDED),
                  changedFiles=sorted(FILES - ADDED), deletedFiles=[], databaseMigrations=[MIGRATION], migrationSha256=sha(contents['platform/storage/migrations/' + MIGRATION]),
                  permissionChanges=['authenticated-sdk-connect-only'], newPublicPorts=[], ubuntuChanges=[], sdkActions=0)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'cloud.delta.json.gz').write_bytes(packed)
    (destination / 'expected-manifest.json').write_bytes(manifest)
    (destination / 'candidate-summary.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.baseline, args.destination), sort_keys=True))
