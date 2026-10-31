"""Fixed C3d camera-only compact renewals. Review is read-only by default.

Only four public source files may change; the single added file is compact-grant.
No database, permission, environment, port, Robot or showcase configuration changes.
Unfrozen release/package pins deliberately prevent all operation.
"""
import argparse
import base64
import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request

try:
    import fcntl
except ImportError:
    fcntl = None

ROOT = Path('/var/backups/thirdhand/access-C3d-compact-camera-20261031')
CURRENT = Path('/opt/thirdhand-stage/current')
OLD = Path('/opt/thirdhand-stage/releases/04cc19054caa45a6')
NEW = Path('/opt/thirdhand-stage/releases/986ca7c282e532a8')
OLD_MANIFEST = '04cc19054caa45a6406450ac058caf76935be4d51e0590499d28bac5a2fa4917'
NEW_MANIFEST = '986ca7c282e532a83b91195759c7328c8ec906d57bd4113c9ccb3ac6ac9cafdb'
PACKAGE_SHA = '55288baf01dcc7fc1cc1af998e680f25ab343fd563ab9eedbf54854cd79fdb7f'
OLD_FILES_COUNT = 4624
ADDED_FILE = 'services/cloud-api/src/media/compact-grant.js'
EXISTING_CHANGES = {'services/device-relay/src/server.js', 'services/cloud-api/src/media/policy.js',
                    'services/cloud-api/src/device-runtime.js'}
EXPECTED_FILES = EXISTING_CHANGES | {ADDED_FILE}
ENVIRONMENT = Path('/etc/thirdhand-stage/cloud.env')
SHOWCASE = Path('/www/wwwroot/uiea-thirdhand-static/index.html')
RESTART_UNITS = ('thirdhand-stage.service',)


class DeploymentError(Exception):
    def __init__(self, code, rollback=None):
        super().__init__(code)
        self.code, self.rollback = code, rollback


def require(value, code):
    if not value:
        raise DeploymentError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_path(path):
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'UNSAFE_PATH')
    return path


def regular(path, maximum=16 * 1024 * 1024):
    safe_path(path)
    require(path.is_file() and path.stat().st_size <= maximum, 'REGULAR_BOUNDED_FILE_REQUIRED')
    return path.read_bytes()


def require_identity():
    require(os.name == 'posix' and fcntl is not None and os.getuid() == os.geteuid() == 0,
            'LINUX_ROOT_REQUIRED')
    safe_path(ROOT)
    require(ROOT.is_dir() and ROOT.stat().st_uid == 0 and ROOT.stat().st_mode & 0o077 == 0,
            'PRIVATE_REVIEW_DIRECTORY_REQUIRED')


def frozen():
    require(all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                for value in (PACKAGE_SHA, OLD_MANIFEST, NEW_MANIFEST))
            and NEW.parent == OLD.parent and 'UNFROZEN' not in NEW.name, 'UNFROZEN_CANDIDATE')


@contextlib.contextmanager
def installation_lock():
    path = safe_path(ROOT / 'installer.lock')
    with path.open('a') as stream:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DeploymentError('INSTALLER_BUSY') from None
        yield


def check_release(directory, manifest_sha):
    safe_path(directory)
    require(directory.parent == OLD.parent, 'UNSAFE_RELEASE_ROOT')
    raw = regular(directory / 'manifest.json')
    require(sha(raw) == manifest_sha, 'RELEASE_MANIFEST_CHANGED')
    manifest = json.loads(raw)
    files = manifest['files']
    actual = set()
    for path, directories, names in os.walk(directory, followlinks=False):
        for name in directories:
            safe_path(Path(path) / name)
        for name in names:
            child = safe_path(Path(path) / name)
            require(child.is_file(), 'UNSAFE_RELEASE_FILE')
            actual.add(child.relative_to(directory).as_posix())
    require(actual == set(files) | {'manifest.json'}, 'RELEASE_INVENTORY_CHANGED')
    for name, digest in files.items():
        path = directory / name
        require(path.is_relative_to(directory) and sha(regular(path)) == digest, 'RELEASE_SOURCE_CHANGED')
    return manifest


def read_package(previous):
    raw = regular(ROOT / 'cloud.delta.json.gz', 4 * 1024 * 1024)
    require(sha(raw) == PACKAGE_SHA, 'PACKAGE_DIGEST_MISMATCH')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded = stream.read(16 * 1024 * 1024 + 1)
    require(len(decoded) <= 16 * 1024 * 1024, 'PACKAGE_TOO_LARGE')
    package = json.loads(decoded)
    require(package.get('format') == 1 and package.get('oldRelease') == str(OLD)
            and package.get('newRelease') == str(NEW)
            and package.get('oldManifestSha256') == OLD_MANIFEST
            and package.get('manifestSha256') == NEW_MANIFEST, 'PACKAGE_RELEASE_MISMATCH')
    require(isinstance(package.get('changes'), dict) and set(package['changes']) == EXPECTED_FILES,
            'PACKAGE_SCOPE_MISMATCH')
    before = previous['files']
    require(len(before) == OLD_FILES_COUNT and EXISTING_CHANGES <= set(before)
            and ADDED_FILE not in before, 'BASELINE_INVENTORY_MISMATCH')
    require(package.get('beforeHashes') == {name: before[name] for name in EXISTING_CHANGES},
            'BEFORE_HASH_MISMATCH')
    manifest_raw = base64.b64decode(package['manifestBase64'], validate=True)
    require(sha(manifest_raw) == NEW_MANIFEST, 'NEW_MANIFEST_MISMATCH')
    after = json.loads(manifest_raw)['files']
    require(set(after) == set(before) | {ADDED_FILE} and len(after) == OLD_FILES_COUNT + 1,
            'NEW_INVENTORY_MISMATCH')
    require({name for name in before if before[name] != after[name]} == EXISTING_CHANGES,
            'EXTRA_SOURCE_CHANGES')
    contents = {name: base64.b64decode(data, validate=True) for name, data in package['changes'].items()}
    require(all(sha(raw) == after[name] for name, raw in contents.items()), 'NEW_SOURCE_DIGEST_MISMATCH')
    return manifest_raw, contents


def active_leases():
    result = subprocess.run(['/usr/sbin/runuser', '-u', 'postgres', '--',
        '/usr/lib/postgresql/17/bin/psql', '-X', '-q', '-At', '-h', '/run/thirdhand-stage-db',
        '-p', '55440', '-d', 'thirdhand_stage', '-c',
        "SELECT count(*) FROM ops.control_leases WHERE state IN ('requested','active','revoking')"],
        check=True, capture_output=True, text=True)
    require(result.stdout.strip() == '0', 'CONTROL_LEASE_OCCUPIED')


def current_target():
    require(CURRENT.is_symlink() and CURRENT.resolve() in (OLD, NEW), 'CURRENT_RELEASE_CHANGED')
    return CURRENT.resolve()


def protected_hashes():
    return {name: sha(regular(path)) for name, path in (('environment', ENVIRONMENT), ('showcase', SHOWCASE))}


def checkpoint(invariants):
    current_target()
    check_release(OLD, OLD_MANIFEST)
    require(protected_hashes() == invariants, 'PROTECTED_CONFIGURATION_CHANGED')
    active_leases()


def switch(target):
    require(target in (OLD, NEW) and safe_path(target) == target, 'UNSAFE_SWITCH_TARGET')
    temporary = CURRENT.with_name('current.C3d-compact-camera')
    require(not temporary.exists() and not temporary.is_symlink(), 'SWITCH_PATH_OCCUPIED')
    temporary.symlink_to(target)
    temporary.replace(CURRENT)


def restart():
    subprocess.run(['systemctl', 'restart', RESTART_UNITS[0]], check=True, capture_output=True)
    for attempt in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:3202/healthz', timeout=2) as response:
                require(json.load(response).get('deviceControl') == 'explicit-read-only', 'READ_ONLY_API_REQUIRED')
            return
        except Exception:
            if attempt == 29:
                raise DeploymentError('API_HEALTH_UNCONFIRMED') from None
            time.sleep(0.25)


def save_backup(invariants):
    value = {'oldRelease': str(OLD), 'oldManifestSha256': OLD_MANIFEST, 'protectedSha256': invariants}
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    path = ROOT / 'before-public.json'
    if path.exists() or path.is_symlink():
        require(regular(path) == raw, 'BEFORE_BACKUP_CHANGED')
    else:
        with path.open('xb') as stream:
            stream.write(raw)
        path.chmod(0o600)


def rollback_locked():
    # Never inspect the upload package or damaged NEW to restore verified OLD.
    before = json.loads(regular(ROOT / 'before-public.json', 16384))
    require(before.get('oldRelease') == str(OLD) and before.get('oldManifestSha256') == OLD_MANIFEST,
            'BEFORE_BACKUP_CHANGED')
    invariants = before['protectedSha256']
    checkpoint(invariants)
    if current_target() == NEW:
        switch(OLD)
    checkpoint(invariants)
    restart()
    checkpoint(invariants)
    require(current_target() == OLD, 'ROLLBACK_UNCONFIRMED')
    return {'rolledBack': True, 'current': str(OLD), 'sdkActions': 0, 'motionCommands': 0}


def execute(apply=False, rollback=False):
    require_identity(); frozen()
    if apply or rollback:
        with installation_lock():
            return rollback_locked() if rollback else apply_locked()
    return prepare()[3]


def prepare():
    previous = check_release(OLD, OLD_MANIFEST)
    require(current_target() == OLD, 'CURRENT_RELEASE_CHANGED')
    require(not NEW.exists() and not NEW.is_symlink(), 'CANDIDATE_PATH_OCCUPIED')
    manifest_raw, contents = read_package(previous)
    invariants = protected_hashes()
    checkpoint(invariants)
    report = {'applied': False, 'oldRelease': str(OLD), 'newRelease': str(NEW),
              'changes': sorted(contents), 'sdkActions': 0, 'motionCommands': 0,
              'databaseMigrations': [], 'newPublicPorts': [], 'permissionChanges': []}
    return manifest_raw, contents, invariants, report


def apply_locked():
    manifest_raw, contents, invariants, report = prepare()
    save_backup(invariants)
    shutil.copytree(OLD, NEW, symlinks=False)
    for name, raw in contents.items():
        path = NEW / name
        path.write_bytes(raw); path.chmod(0o644)
    (NEW / 'manifest.json').write_bytes(manifest_raw)
    check_release(NEW, NEW_MANIFEST)
    switched = False
    try:
        checkpoint(invariants)
        switch(NEW); switched = True
        checkpoint(invariants)
        restart()
        checkpoint(invariants)
        require(current_target() == NEW, 'APPLICATION_UNCONFIRMED')
    except BaseException as error:
        outcome = 'not-needed'
        if switched:
            try:
                rollback_locked(); outcome = 'restored'
            except Exception:
                outcome = 'blocked'
        raise DeploymentError(error.code if isinstance(error, DeploymentError) else 'APPLICATION_FAILED',
                              rollback=outcome) from None
    return {**report, 'applied': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true'); mode.add_argument('--rollback', action='store_true')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(execute(args.apply, args.rollback), sort_keys=True))
        return 0
    except Exception as error:
        report = {'applied': False, 'code': error.code if isinstance(error, DeploymentError) else 'REVIEW_FAILED'}
        if isinstance(error, DeploymentError) and error.rollback:
            report['rollback'] = error.rollback
        print(json.dumps(report, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
