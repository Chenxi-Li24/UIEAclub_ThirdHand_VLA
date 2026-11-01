"""Build the C8 cloud delta from a fixed Git commit, never a dirty worktree.

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
SOURCE = '7e65b5d3b59fb7359dec1262d1f7a31c9a63139d'
OLD_SHA = '1fdfb95e8d905105b94238fb1749bcf21f368045e8301d519c0e509d160b97b8'
OLD = '/opt/thirdhand-stage/releases/' + OLD_SHA[:16]
FILES = {'apps/web/public/css/' + n + '.css' for n in ('history', 'workspace-layouts')} | {
    'apps/web/public/js/' + n + '.js' for n in (
        'account-security', 'account-settings', 'admin-access', 'admin-control',
        'camera-view', 'classic-shell', 'device-state', 'history-page',
        'i18n-cloud-catalog', 'i18n-history-catalog', 'onboarding', 'status-lights',
        'workspace-navigation', 'workspace-session', 'workspace-shell', 'workspace-startup')
} | {'services/cloud-api/src/' + n + '.js' for n in (
    'device-runtime', 'main', 'routes/control', 'routes/session', 'server', 'workspace-pages')
} | {'services/device-relay/src/' + n + '.js' for n in ('latest-state', 'server')}
ADDED = {'apps/web/public/js/device-state.js', 'apps/web/public/js/workspace-navigation.js',
         'services/device-relay/src/latest-state.js'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_bytes(name):
    return subprocess.run(['git', 'show', SOURCE + ':' + name], cwd=REPO,
                          capture_output=True, check=True).stdout


def build(baseline, destination, read_source=source_bytes):
    raw = baseline.read_bytes()
    if sha(raw) != OLD_SHA:
        raise ValueError('C7 baseline manifest changed')
    before = json.loads(raw)
    if len(before['files']) != 4653 or not FILES - ADDED <= before['files'].keys() or ADDED & before['files'].keys():
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
                  changedFiles=sorted(FILES - ADDED), deletedFiles=[], databaseMigrations=[],
                  permissionChanges=[], newPublicPorts=[], ubuntuChanges=[], sdkActions=0)
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
