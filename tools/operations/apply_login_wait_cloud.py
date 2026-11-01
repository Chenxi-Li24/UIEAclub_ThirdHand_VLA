"""Login feedback fixed cloud-only candidate; default review has no server mutation.

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

ROOT = Path('/var/backups/thirdhand/access-login-wait-20261101')
BASE = Path('/var/backups/thirdhand/access-C3f-camera-ui-20261101/apply_camera_ui_cloud.py')
BASE_SHA = 'd10eaa3e631f873d394f501e36588d6b4f037dbfbd2cc6145b63e4ba09ac2f4f'
OLD_SHA = '4688a5dfdcf768109296765b7937fd8bbb47ec22bd27ae4b25a11562590da1f8'
NEW_SHA = 'dfbca02d47ca7f4020354567482265c5f2645a76e509a3f82cf4d23641d5aa4e'
PACKAGE_SHA = '7f697e5f83a085a63d631ed81d3180139ccfbd86c4eaca261e80bd1d64eeddbe'
FILES = {'apps/web/public/css/auth.css', 'apps/web/public/js/auth-page.js', 'apps/web/public/js/i18n-auth-catalog.js'}
ADDED = set()


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
    base.require(len(before) == 4656 and FILES - ADDED <= before.keys()
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
    base.OLD_FILES_COUNT, base.EXPECTED_FILES = 4656, FILES
    base.read_package = lambda before: read_package(base, before)
    base.staging_path = lambda: base.NEW.with_name('.' + base.NEW.name + '.login-wait-staging')
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
