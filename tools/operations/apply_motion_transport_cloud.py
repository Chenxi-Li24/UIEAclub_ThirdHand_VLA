"""Fixed C3c read-only cloud transport delta. Default validates and reports only.

No identity, database, SDK, Robot, media port or permission configuration changes.
The reviewed package is pinned before decoding; --apply creates a new release
and restarts only the API. --rollback restores only the pinned prior release.
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

ROOT = Path('/var/backups/thirdhand/access-C3c-transport-20261031')
CURRENT = Path('/opt/thirdhand-stage/current')
OLD = Path('/opt/thirdhand-stage/releases/6187bbbe8ec4d5e8')
NEW = Path('/opt/thirdhand-stage/releases/04cc19054caa45a6')
OLD_MANIFEST = 'e6d791d66ca8ad1f59a85e076df5de360cea6ec9ce746643caaf9507baf55ba4'
NEW_MANIFEST = '04cc19054caa45a6406450ac058caf76935be4d51e0590499d28bac5a2fa4917'
PACKAGE_SHA = '2ed1012f84bcd467c5b02ba67c921cd7e134ddceec851b82d5867eea5edc20ca'
EXPECTED_FILES = {'services/cloud-api/src/control/websocket.js'}
RESTART_UNITS = ('thirdhand-stage.service',)


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def validate_scope(package):
    require(package.get('format') == 1 and package.get('oldRelease') == str(OLD)
            and package.get('newRelease') == str(NEW), 'Unexpected release target')
    require(package.get('oldManifestSha256') == OLD_MANIFEST
            and package.get('manifestSha256') == NEW_MANIFEST, 'Unexpected release manifest')
    require(isinstance(package.get('changes'), dict)
            and set(package['changes']) == EXPECTED_FILES, 'Unexpected change scope')


def read_package(path):
    require(path.is_file() and not path.is_symlink(), 'Regular package required')
    raw = path.read_bytes()
    require(sha(raw) == PACKAGE_SHA, 'Reviewed package digest mismatch')
    package = json.loads(gzip.decompress(raw))
    validate_scope(package)
    return package


def active_leases():
    result = subprocess.run(['/usr/sbin/runuser', '-u', 'postgres', '--',
        '/usr/lib/postgresql/17/bin/psql', '-X', '-q', '-At', '-h', '/run/thirdhand-stage-db',
        '-p', '55440', '-d', 'thirdhand_stage', '-c',
        "SELECT count(*) FROM ops.control_leases WHERE state IN ('requested','active','revoking')"],
        check=True, capture_output=True, text=True)
    require(result.stdout.strip() == '0', 'Control lease still occupied; do not restart API')


def check_release(root, expected_manifest):
    require(root.parent == OLD.parent and root.resolve() == root and not root.is_symlink(), 'Unsafe release root')
    raw = (root / 'manifest.json').read_bytes()
    require(sha(raw) == expected_manifest, 'Installed manifest differs from reviewed baseline')
    manifest = json.loads(raw)
    actual_files = set()
    for directory, names, files in os.walk(root, followlinks=False):
        for name in names:
            child = Path(directory) / name
            require(child.resolve() == child and not child.is_symlink(), 'Linked release directory rejected')
        for name in files:
            child = Path(directory) / name
            require(child.resolve() == child and child.is_file() and not child.is_symlink(), 'Linked release file rejected')
            actual_files.add(child.relative_to(root).as_posix())
    require(actual_files == set(manifest['files']) | {'manifest.json'}, 'Unexpected installed file inventory')
    for name, digest in manifest['files'].items():
        path = root / name
        require(path.resolve() == path and path.is_file() and sha(path.read_bytes()) == digest,
                'Installed source hash/path mismatch: ' + name)
    return manifest


def health():
    for attempt in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:3202/healthz', timeout=2) as response:
                require(json.load(response).get('deviceControl') == 'explicit-read-only', 'Read-only API health required')
            return
        except Exception:
            if attempt == 29:
                raise
            time.sleep(0.25)


def switch(target):
    require(target in (OLD, NEW) and target.resolve() == target, 'Unsafe switch target')
    temporary = CURRENT.with_name('current.C3c-transport')
    require(not temporary.exists() and not temporary.is_symlink(), 'Temporary switch path occupied')
    temporary.symlink_to(target)
    temporary.replace(CURRENT)


def restart():
    for unit in RESTART_UNITS:
        subprocess.run(['systemctl', 'restart', unit], check=True)
    health()


def main(apply=False, rollback=False):
    require(os.name == 'posix' and os.geteuid() == 0, 'Linux root required')
    require(ROOT.resolve() == ROOT and ROOT.is_dir() and not ROOT.is_symlink(), 'Private fixed review directory required')
    os.umask(0o077)
    previous = check_release(OLD, OLD_MANIFEST)
    active_leases()
    if rollback:
        require(CURRENT.is_symlink() and CURRENT.resolve() == NEW, 'Current release is not this rollout')
        # A damaged candidate is a reason to restore the verified old release,
        # not a precondition that may prevent the restoration.
        switch(OLD)
        restart()
        print(json.dumps({'rolledBack': True, 'current': str(OLD), 'sdkActions': 0, 'motionCommands': 0}))
        return
    package = read_package(ROOT / 'cloud.delta.json.gz')
    require(CURRENT.is_symlink() and CURRENT.resolve() == OLD, 'Current release changed; stop for review')
    require(not NEW.exists() and not NEW.is_symlink(), 'Candidate release path already exists')
    manifest_bytes = base64.b64decode(package['manifestBase64'], validate=True)
    require(sha(manifest_bytes) == NEW_MANIFEST, 'New manifest digest mismatch')
    expected = json.loads(manifest_bytes)
    require(set(expected['files']) == set(previous['files']), 'Unexpected file inventory change')
    require({name for name, value in expected['files'].items() if value != previous['files'][name]} == EXPECTED_FILES,
            'Delta outside the one-file scope')
    contents = {name: base64.b64decode(value, validate=True) for name, value in package['changes'].items()}
    require(package['beforeHashes'] == {name: previous['files'][name] for name in EXPECTED_FILES}, 'Before hash mismatch')
    require(all(sha(data) == expected['files'][name] for name, data in contents.items()), 'New source hash mismatch')
    environment = Path('/etc/thirdhand-stage/cloud.env')
    showcase = Path('/www/wwwroot/uiea-thirdhand-static/index.html')
    invariants = {path: sha(path.read_bytes()) for path in (environment, showcase)}
    report = {'applied': False, 'oldRelease': str(OLD), 'newRelease': str(NEW), 'changes': sorted(contents),
              'newPublicPorts': [], 'databaseMigrations': [], 'permissionChanges': [],
              'sdkActions': 0, 'motionCommands': 0, 'authConfigurationUnchanged': True}
    (ROOT / 'cloud-review.json').write_text(json.dumps(report, indent=2))
    if not apply:
        print(json.dumps(report))
        return
    (ROOT / 'cloud-before-release.txt').write_text(str(OLD))
    # The source and final targets were resolved above. No old release is removed.
    shutil.copytree(OLD, NEW, symlinks=False)
    for name, data in contents.items():
        (NEW / name).write_bytes(data)
        (NEW / name).chmod(0o644)
    (NEW / 'manifest.json').write_bytes(manifest_bytes)
    check_release(NEW, NEW_MANIFEST)
    switched = False
    try:
        active_leases()
        switch(NEW)
        switched = True
        restart()
        require(all(sha(path.read_bytes()) == digest for path, digest in invariants.items()), 'Protected configuration changed')
    except Exception:
        if switched:
            switch(OLD)
            restart()
        raise
    report.update(applied=True, completedAtUnix=time.time())
    (ROOT / 'cloud-applied.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    main(args.apply, args.rollback)
