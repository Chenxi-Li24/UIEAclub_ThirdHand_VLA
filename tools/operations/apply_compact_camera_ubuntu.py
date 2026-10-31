"""Fixed C3d camera-publisher source switch; default review never writes.

Only the existing camera publisher PYTHONPATH drop-in is updated. No edge,
Robot, camera-source, SDK, CAN, private configuration or database mutation.
Unfrozen pins deliberately reject operation until the reviewed package exists.
"""
import argparse
import contextlib
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tarfile
import time
import urllib.request

try:
    import fcntl
except ImportError:
    fcntl = None

DEVICE_ID = 'ee625a57-049a-4c5d-92e1-9578ab9d21c3'
BASE = Path('/home/nieqingcao/.local/share/thirdhand-stage-device/20261031')
CAMERA_BASE = Path('/home/nieqingcao/.local/share/thirdhand-stage-camera/20261031')
CANDIDATE = BASE / 'incoming/compact-camera-candidate'
REVIEW = CAMERA_BASE / 'compact-camera-review-C3d'
OLD = CAMERA_BASE / 'source-5bf518471ff7aa60'
NEW = CAMERA_BASE / 'source-4e49ee54335e9af3'
OLD_MANIFEST = '4f5202619c9957377396532c8d889e6b704b6529c7f50cb76c310e16c015437a'
NEW_SOURCE_DIGEST = '4e49ee54335e9af34f3fffd365e6a0f9b776051cb8f03f9986220ae69f5110d6'
NEW_CLOUD = '/opt/thirdhand-stage/releases/986ca7c282e532a8'
OLD_CLOUD = '/opt/thirdhand-stage/releases/04cc19054caa45a6'
PINS = {'camera.source.tar.gz': 'f57ed683b2d406d87817caf4ad25e2ea63ccf1e569c497207f3440262024b142',
        'baseline-public.json': 'c3481f0618852c8d409f2f863dd94d49806417a9faedc474ed307e0c5820ded3',
        'camera-publisher-compact.conf.template': 'd1b6632d07125f68f126cbc3d168fb14c9b7f0a9ed48d0fda138d324eb2f9d6a'}
UNIT = 'thirdhand-stage-camera-publisher.service'
UNIT_FILE = Path('/etc/systemd/system') / UNIT
DROPIN = UNIT_FILE.with_name(UNIT + '.d') / '50-C3c-transport.conf'
UNIT_SHA = 'c604a65a072f9cc83d1ebe0d08c72f8f95c7faf12148fd64f99c2c0dc0c42e51'
TOKEN_FILE = BASE / 'private/edge.token'
ADDED_FILE = 'thirdhand_edge/media_renewal.py'
EXISTING_CHANGES = {'thirdhand_edge/media_upload.py', 'thirdhand_edge/media_publisher.py',
                    'thirdhand_edge/camera_runtime.py'}
EXPECTED_CHANGES = EXISTING_CHANGES | {ADDED_FILE}
now = time.time


class InstallError(Exception):
    def __init__(self, code, rollback=None):
        super().__init__(code)
        self.code, self.rollback = code, rollback


def require(value, code):
    if not value:
        raise InstallError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def template(directory):
    return ('[Service]\nEnvironment=PYTHONPATH=' + directory.as_posix() + '\n').encode()


def frozen():
    require(all(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value)
                for value in (*PINS.values(), OLD_MANIFEST, NEW_SOURCE_DIGEST, UNIT_SHA))
            and isinstance(NEW_CLOUD, str) and NEW_CLOUD.startswith('/opt/thirdhand-stage/releases/')
            and 'UNFROZEN' not in NEW.name and NEW.parent == OLD.parent, 'UNFROZEN_CANDIDATE')


def require_identity():
    require(sys.platform == 'linux' and fcntl is not None and sys.version_info >= (3, 11)
            and os.getuid() == os.geteuid() == 1000, 'UBUNTU_UID1000_PYTHON311_REQUIRED')


def safe_path(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'UNSAFE_PATH')
    return path


def regular(path, maximum=2 * 1024 * 1024):
    path = safe_path(path)
    require(path.is_file() and path.stat().st_size <= maximum, 'REGULAR_BOUNDED_FILE_REQUIRED')
    return path.read_bytes()


def read_archive(raw, before):
    entries, total = {}, 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            for item in archive:
                parts = PurePosixPath(item.name).parts
                allowed = item.name == 'source-manifest.json' or (len(parts) == 2 and parts[0] == 'thirdhand_edge'
                    and re.fullmatch(r'[A-Za-z0-9_]+\.py', parts[1]))
                total += item.size
                require(item.isfile() and allowed and '\\' not in item.name and item.name not in entries
                        and 0 <= item.size <= 262144 and total <= 2 * 1024 * 1024, 'UNSAFE_ARCHIVE')
                entries[item.name] = archive.extractfile(item).read()
        manifest = json.loads(entries['source-manifest.json'])
        files = {name: sha(value) for name, value in entries.items() if name != 'source-manifest.json'}
        require(len(before) == 20 and ADDED_FILE not in before and EXISTING_CHANGES <= set(before)
                and len(files) == 21 and set(files) == set(before) | {ADDED_FILE}
                and manifest.get('format') == 1 and manifest.get('role') == 'camera-compact-candidate'
                and manifest.get('automaticSdkConnect') is False and manifest.get('files') == files
                and manifest.get('baselineFiles') == before
                and set(manifest.get('changedFiles', [])) == EXPECTED_CHANGES
                and {name for name in before if before[name] != files[name]} == EXISTING_CHANGES
                and sha(canonical(files)) == NEW_SOURCE_DIGEST, 'ARCHIVE_MANIFEST_MISMATCH')
        for name, raw in entries.items():
            if name.endswith('.py'):
                compile(raw, name, 'exec', dont_inherit=True)
        return entries
    except InstallError:
        raise
    except Exception:
        raise InstallError('ARCHIVE_INVALID') from None


def baseline(raw):
    require(sha(raw) == PINS['baseline-public.json'], 'BASELINE_DIGEST_MISMATCH')
    value = json.loads(raw)['camera']
    require(value['source'] == OLD.as_posix() and value['manifestSha256'] == OLD_MANIFEST
            and len(value['files']) == 20 and ADDED_FILE not in value['files'], 'BASELINE_TARGET_MISMATCH')
    return value


def load_candidate():
    frozen()
    blobs = {name: regular(CANDIDATE / name) for name in PINS}
    require(all(sha(blobs[name]) == digest for name, digest in PINS.items()), 'CANDIDATE_DIGEST_MISMATCH')
    before = baseline(blobs['baseline-public.json'])
    require(blobs['camera-publisher-compact.conf.template'] == template(NEW), 'FIXED_TEMPLATE_MISMATCH')
    return {'before': before, 'baselineRaw': blobs['baseline-public.json'],
            'entries': read_archive(blobs['camera.source.tar.gz'], before['files'])}


def source_inventory(directory):
    safe_path(directory)
    files = {}
    for path in directory.rglob('*'):
        safe_path(path)
        require(path.is_file() or path == directory / 'thirdhand_edge', 'SOURCE_INVENTORY_CHANGED')
        if path.is_file():
            files[path.relative_to(directory).as_posix()] = sha(regular(path))
    return files


def verify_old(payload):
    expected = {**payload['before']['files'], 'source-manifest.json': OLD_MANIFEST}
    require(source_inventory(OLD) == expected, 'OLD_SOURCE_CHANGED')


def verify_new(entries):
    require(source_inventory(NEW) == {name: sha(raw) for name, raw in entries.items()}, 'NEW_SOURCE_CHANGED')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise InstallError('ROBOT_STATUS_UNAVAILABLE')


def robot_state():
    try:
        info = TOKEN_FILE.stat()
        require(info.st_uid == 1000 and info.st_mode & 0o077 == 0, 'ROBOT_STATUS_UNAVAILABLE')
        token = regular(TOKEN_FILE, 128).decode('ascii').strip()
        require(re.fullmatch('[a-f0-9]{64}', token), 'ROBOT_STATUS_UNAVAILABLE')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        def get(path, headers=None):
            with opener.open(urllib.request.Request('http://127.0.0.1:3000' + path, headers=headers or {}), timeout=3) as response:
                raw = response.read(65537)
                require(len(raw) <= 65536 and response.headers.get_content_type() == 'application/json',
                        'ROBOT_STATUS_UNAVAILABLE')
                return json.loads(raw)
        context = get('/edge-control/v1/context', {'X-ThirdHand-Edge-Token': token})
        health = get('/health')
        require(context.get('deviceId') == DEVICE_ID and health.get('mode') == 'hardware', 'ROBOT_STATUS_UNAVAILABLE')
        return {'sdkConnected': context.get('sdkConnected'), 'readOnly': context.get('readOnly'),
                'connected': health['robot'].get('connected'), 'moving': health['robot'].get('moving')}
    except InstallError:
        raise
    except Exception:
        raise InstallError('ROBOT_STATUS_UNAVAILABLE') from None


def cloud_review(path, digest, rollback=False):
    require(path and isinstance(digest, str) and re.fullmatch('[a-fA-F0-9]{64}', digest), 'FRESH_CLOUD_REVIEW_REQUIRED')
    path = Path(path); raw = regular(path, 16384); info = path.stat()
    require(os.name != 'posix' or info.st_uid == 1000 and info.st_mode & 0o077 == 0, 'PRIVATE_CLOUD_REVIEW_REQUIRED')
    require(sha(raw) == digest.lower(), 'CLOUD_REVIEW_DIGEST_MISMATCH')
    try:
        value = json.loads(raw)
        checked = datetime.fromisoformat(value['checkedAt'].replace('Z', '+00:00'))
        require(checked.tzinfo is not None and -5 <= now() - checked.timestamp() <= 60, 'CLOUD_REVIEW_STALE')
        require(value.get('verified') is True and value.get('deviceId') == DEVICE_ID
                and type(value.get('activeLeases')) is int and value['activeLeases'] == 0
                and value.get('currentRelease') in ({OLD_CLOUD, NEW_CLOUD} if rollback else {NEW_CLOUD}),
                'CLOUD_REVIEW_NOT_CLEAR')
    except InstallError:
        raise
    except Exception:
        raise InstallError('CLOUD_REVIEW_INVALID') from None


def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    require(result.returncode == 0, 'SERVICE_COMMAND_FAILED')
    return result.stdout


def inspect_unit():
    raw = run(['systemctl', 'show', UNIT, '-p', 'FragmentPath', '-p', 'DropInPaths', '-p', 'Environment', '-p', 'ActiveState', '--no-pager'])
    value = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    env = dict(item.split('=', 1) for item in shlex.split(value.get('Environment', '')) if '=' in item)
    return {'FragmentPath': value.get('FragmentPath'), 'DropInPaths': shlex.split(value.get('DropInPaths', '')),
            'pythonPath': env.get('PYTHONPATH'), 'ActiveState': value.get('ActiveState')}


def check_configuration():
    require(sha(regular(UNIT_FILE)) == UNIT_SHA, 'ORIGINAL_UNIT_CHANGED')
    directory = safe_path(DROPIN.parent)
    require(directory.is_dir(), 'DROPIN_DIRECTORY_CHANGED')
    require(all(path == DROPIN for path in directory.iterdir() if path.name.endswith('.conf')), 'UNKNOWN_DISK_DROPIN')
    require(regular(DROPIN) in (template(OLD), template(NEW)), 'OWNED_DROPIN_CHANGED')
    unit = inspect_unit()
    require(unit['FragmentPath'] == str(UNIT_FILE) and unit['DropInPaths'] == [str(DROPIN)]
            and unit['pythonPath'] in (str(OLD), str(NEW)), 'LOADED_UNIT_CHANGED')
    return unit


def checkpoint(payload, cloud_file=None, cloud_sha=None, *, rollback=False):
    try:
        verify_old(payload)
        unit = check_configuration()
        state = robot_state()
        require(state.get('sdkConnected') is False and state.get('readOnly') is True
                and state.get('connected') is False and state.get('moving') is False, 'ROBOT_STATE_NOT_DISCONNECTED')
        if cloud_file is not None or cloud_sha is not None:
            cloud_review(cloud_file, cloud_sha, rollback=rollback)
        return unit
    except InstallError as error:
        if rollback:
            error.rollback = 'blocked'
        raise


def review(payload, cloud_file=None, cloud_sha=None):
    require_identity(); frozen()
    unit = checkpoint(payload, cloud_file, cloud_sha)
    installed = regular(DROPIN) == template(NEW)
    if installed:
        verify_new(payload['entries'])
    require(unit['pythonPath'] == str(NEW if installed else OLD)
            and unit['ActiveState'] in {'active', 'activating'}, 'SERVICE_CONFIGURATION_UNCONFIRMED')
    return {'mode': 'review', 'installed': installed, 'unit': UNIT, 'cloudReview': 'verifiedFresh' if cloud_file else 'pending',
            'newPythonModules': 21, 'sdkActions': 0, 'motionCommands': 0}


def check_backup_directory():
    safe_path(REVIEW)
    require(REVIEW.is_dir(), 'PRIVATE_BACKUP_REQUIRED')
    if os.name == 'posix':
        require(REVIEW.stat().st_uid == 1000 and REVIEW.stat().st_mode & 0o077 == 0, 'PRIVATE_BACKUP_REQUIRED')


def prepare_backup(payload):
    safe_path(REVIEW); REVIEW.mkdir(mode=0o700, exist_ok=True)
    check_backup_directory()
    for name, raw in {'baseline-public.json': payload['baselineRaw'], 'original-publisher.conf': template(OLD)}.items():
        path = REVIEW / name
        if path.exists() or path.is_symlink():
            require(regular(path) == raw, 'BEFORE_BACKUP_CHANGED')
        else:
            with path.open('xb') as stream: stream.write(raw)
            path.chmod(0o600)


@contextlib.contextmanager
def installation_lock():
    check_backup_directory()
    path = safe_path(REVIEW / 'installer.lock')
    with path.open('a') as stream:
        path.chmod(0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise InstallError('INSTALLER_BUSY') from None
        yield


def install_source(entries):
    safe_path(NEW)
    if NEW.exists():
        verify_new(entries); return
    NEW.mkdir(mode=0o700); (NEW / 'thirdhand_edge').mkdir(mode=0o700)
    for name, raw in entries.items():
        path = NEW / name
        with path.open('xb') as stream: stream.write(raw)
        path.chmod(0o400)
    (NEW / 'thirdhand_edge').chmod(0o500); NEW.chmod(0o500)
    verify_new(entries)


def write_dropin(raw, check):
    stage = REVIEW / ('publisher-new.conf' if raw == template(NEW) else 'publisher-old.conf')
    if stage.exists() or stage.is_symlink():
        require(regular(stage) == raw, 'STAGED_CONFIGURATION_CHANGED')
    else:
        with stage.open('xb') as stream: stream.write(raw)
        stage.chmod(0o600)
    check()
    run(['sudo', '-n', 'install', '-o', 'root', '-g', 'root', '-m', '644', str(stage), str(DROPIN)])
    require(regular(DROPIN) == raw, 'DROPIN_WRITE_UNCONFIRMED')


def restart(check):
    check(); run(['sudo', '-n', 'systemctl', 'daemon-reload'])
    check(); run(['sudo', '-n', 'systemctl', 'restart', UNIT])


def wait_unit(expected):
    for attempt in range(30):
        state = robot_state()
        require(state.get('sdkConnected') is False and state.get('readOnly') is True
                and state.get('connected') is False and state.get('moving') is False, 'ROBOT_STATE_NOT_DISCONNECTED')
        unit = inspect_unit()
        if unit['ActiveState'] == 'active' and unit['pythonPath'] == str(expected):
            return
        if attempt < 29: time.sleep(0.25)
    raise InstallError('SERVICE_HEALTH_UNCONFIRMED')


def rollback_locked(payload, cloud_file, cloud_sha):
    def check(): return checkpoint(payload, cloud_file, cloud_sha, rollback=True)
    # Require clearance even when no optional receipt arguments were supplied.
    cloud_review(cloud_file, cloud_sha, rollback=True)
    check()
    require(regular(REVIEW / 'original-publisher.conf') == template(OLD), 'BEFORE_BACKUP_CHANGED')
    if regular(DROPIN) != template(OLD):
        write_dropin(template(OLD), check)
    restart(check)
    wait_unit(OLD)
    check()
    require(regular(DROPIN) == template(OLD), 'ROLLBACK_UNCONFIRMED')
    return {'rolledBack': True, 'unit': UNIT, 'snapshotsAndStateRetained': True, 'sdkActions': 0, 'motionCommands': 0}


def execute_rollback(cloud_file, cloud_sha):
    require_identity(); frozen()
    check_backup_directory()
    with installation_lock():
        raw = regular(REVIEW / 'baseline-public.json')
        payload = {'before': baseline(raw), 'baselineRaw': raw}
        try:
            return rollback_locked(payload, cloud_file, cloud_sha)
        except InstallError as error:
            error.rollback = 'blocked'
            raise


def apply(payload, cloud_file, cloud_sha):
    cloud_review(cloud_file, cloud_sha)
    before = review(payload, cloud_file, cloud_sha)
    if before['installed']:
        return {'applied': True, 'alreadyApplied': True, 'sdkActions': 0, 'motionCommands': 0}
    prepare_backup(payload)
    with installation_lock():
        if review(payload, cloud_file, cloud_sha)['installed']:
            return {'applied': True, 'alreadyApplied': True, 'sdkActions': 0, 'motionCommands': 0}
        touched = False
        def check(): return checkpoint(payload, cloud_file, cloud_sha)
        try:
            install_source(payload['entries'])
            check(); touched = True
            write_dropin(template(NEW), check)
            restart(check)
            wait_unit(NEW)
            check()
            require(review(payload, cloud_file, cloud_sha)['installed'], 'APPLICATION_UNCONFIRMED')
        except BaseException as error:
            outcome = 'not-needed'
            if touched:
                try:
                    rollback_locked(payload, cloud_file, cloud_sha); outcome = 'restored'
                except Exception:
                    outcome = 'blocked'
            raise InstallError(error.code if isinstance(error, InstallError) else 'APPLICATION_FAILED', rollback=outcome) from None
    return {'applied': True, 'unit': UNIT, 'sdkActions': 0, 'motionCommands': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true'); mode.add_argument('--rollback', action='store_true')
    parser.add_argument('--cloud-review-file', type=Path); parser.add_argument('--cloud-review-sha256')
    args = parser.parse_args(argv)
    try:
        require_identity(); frozen()
        if args.rollback:
            result = execute_rollback(args.cloud_review_file, args.cloud_review_sha256)
        else:
            result = (apply if args.apply else review)(load_candidate(), args.cloud_review_file, args.cloud_review_sha256)
        print(json.dumps(result, sort_keys=True)); return 0
    except Exception as error:
        result = {'applied': False, 'code': error.code if isinstance(error, InstallError) else 'REVIEW_FAILED'}
        if isinstance(error, InstallError) and error.rollback: result['rollback'] = error.rollback
        print(json.dumps(result, sort_keys=True)); return 2


if __name__ == '__main__':
    raise SystemExit(main())
