"""C8a fixed cloud-only candidate; default review has no server mutation.

No Ubuntu, Nginx, credentials, permissions, migrations or SDK actions.
Requires the already installed and digest-pinned deployment guard.
"""
import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import types

ROOT = Path('/var/backups/thirdhand/access-C8a-ui-sdk-20261101')
BASE = Path('/var/backups/thirdhand/access-C3f-camera-ui-20261101/apply_camera_ui_cloud.py')
BASE_SHA = 'd10eaa3e631f873d394f501e36588d6b4f037dbfbd2cc6145b63e4ba09ac2f4f'
OLD_SHA = '1fdfb95e8d905105b94238fb1749bcf21f368045e8301d519c0e509d160b97b8'
NEW_SHA = '5808d2436598e10e9858fabb359ed8099e39c6e8e86183f960b30bdde8ed7ab5'
PACKAGE_SHA = '50f7b191215bab2a43d45435d9f6febf95bab1e83408fa35d922309fa9a4b5ec'
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


def read_package(base, previous):
    raw = base.regular(ROOT / 'cloud.delta.json.gz', 4 * 1024 * 1024)
    base.require(base.sha(raw) == PACKAGE_SHA, 'PACKAGE_DIGEST_MISMATCH')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded = stream.read(16 * 1024 * 1024 + 1)
    base.require(len(decoded) <= 16 * 1024 * 1024, 'PACKAGE_TOO_LARGE')
    package = json.loads(decoded)
    base.require(package.get('format') == 1 and package.get('oldRelease') == str(base.OLD)
                 and package.get('newRelease') == str(base.NEW)
                 and package.get('oldManifestSha256') == OLD_SHA
                 and package.get('manifestSha256') == NEW_SHA, 'PACKAGE_RELEASE_MISMATCH')
    before = previous['files']
    base.require(len(before) == 4653 and FILES - ADDED <= before.keys()
                 and not ADDED & before.keys(), 'BASELINE_INVENTORY_MISMATCH')
    base.require(set(package.get('changes', {})) == FILES, 'PACKAGE_SCOPE_MISMATCH')
    base.require(package.get('beforeHashes') == {n: before.get(n) for n in FILES}, 'BEFORE_HASH_MISMATCH')
    manifest_raw = base64.b64decode(package['manifestBase64'], validate=True)
    base.require(base.sha(manifest_raw) == NEW_SHA, 'NEW_MANIFEST_MISMATCH')
    manifest = json.loads(manifest_raw)
    after = manifest['files']
    base.require(set(after) == set(before) | ADDED and len(after) == 4656, 'NEW_INVENTORY_MISMATCH')
    base.require({n for n in after if before.get(n) != after[n]} == FILES, 'EXTRA_SOURCE_CHANGES')
    base.require({k: v for k, v in manifest.items() if k != 'files'} ==
                 {k: v for k, v in previous.items() if k != 'files'}, 'MANIFEST_METADATA_CHANGED')
    contents = {n: base64.b64decode(v, validate=True) for n, v in package['changes'].items()}
    base.require(all(base.sha(v) == after[n] for n, v in contents.items()), 'NEW_SOURCE_DIGEST_MISMATCH')
    return manifest_raw, contents


def configure(base):
    base.ROOT = ROOT
    base.OLD = Path('/opt/thirdhand-stage/releases/' + OLD_SHA[:16])
    base.NEW = Path('/opt/thirdhand-stage/releases/' + NEW_SHA[:16])
    base.OLD_MANIFEST, base.NEW_MANIFEST, base.PACKAGE_SHA = OLD_SHA, NEW_SHA, PACKAGE_SHA
    base.OLD_FILES_COUNT, base.EXPECTED_FILES = 4653, FILES
    base.read_package = lambda before: read_package(base, before)
    base.staging_path = lambda: base.NEW.with_name('.' + base.NEW.name + '.C8a-staging')
    return base


def execute(apply=False, rollback=False):
    if BASE.is_symlink() or BASE.resolve() != BASE:
        raise ValueError('Unsafe deployment guard')
    raw = BASE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError('Deployment guard changed')
    module = types.ModuleType('verified_c8_guard')
    exec(compile(raw, str(BASE), 'exec'), module.__dict__)
    return configure(module).execute(apply=apply, rollback=rollback)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    print(json.dumps(execute(args.apply, args.rollback), sort_keys=True))
