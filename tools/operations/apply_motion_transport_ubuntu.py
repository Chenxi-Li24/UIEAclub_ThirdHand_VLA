"""Review/apply the fixed read-only C3c Ubuntu transport candidate.

Run as nieqingcao (uid 1000) with the existing Python >=3.11 environment.
No deployment happens without --apply; --rollback withdraws only this change.
No SDK, CAN, Robot-service restart, credentials or database mutation is used.
"""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
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
CANDIDATE_DIGEST = '0a727ed3a6caa651f1a89144f16d94fea8964d3527af0714373223fbe9d37fb8'
BASE = Path('/home/nieqingcao/.local/share/thirdhand-stage-device/20261031')
CAMERA_BASE = Path('/home/nieqingcao/.local/share/thirdhand-stage-camera/20261031')
CANDIDATE = BASE / 'incoming/transport-candidate-0a727ed3a6caa651'
OLD_AGENT, NEW_AGENT = BASE / 'agent-source', BASE / 'agent-source-aef304c8c1efc5de'
OLD_CAMERA, NEW_CAMERA = CAMERA_BASE / 'source-e9c8e33a97903125', CAMERA_BASE / 'source-5bf518471ff7aa60'
REVIEW = BASE / 'transport-review-0a727ed3a6caa651'
EDGE_UNIT = 'thirdhand-stage-edge-read-only.service'
CAMERA_UNIT = 'thirdhand-stage-camera-publisher.service'
USER_UNIT_FILE = Path('/home/nieqingcao/.config/systemd/user') / EDGE_UNIT
SYSTEM_UNIT_FILE = Path('/etc/systemd/system') / CAMERA_UNIT
USER_DROPIN = USER_UNIT_FILE.with_name(EDGE_UNIT + '.d') / '50-C3c-transport.conf'
SYSTEM_DROPIN = SYSTEM_UNIT_FILE.with_name(CAMERA_UNIT + '.d') / '50-C3c-transport.conf'
TOKEN_FILE = BASE / 'private/edge.token'
NEW_CLOUD = '/opt/thirdhand-stage/releases/04cc19054caa45a6'
OLD_CLOUD = '/opt/thirdhand-stage/releases/6187bbbe8ec4d5e8'
PINS = {
    'agent.source.tar.gz': 'a1c72c502734b8d4288952240b2c8018a6efd2ad3c59e80c771f2a14769c649e',
    'camera.source.tar.gz': '53304aa81891fcd922706cb80bb21288099cf842a3ca44ce460125089e3d8817',
    'baseline-public.json': 'db23f726502b8a0319fcef091ce1d426ce980a6c6fbea30062a253860cc0d5b5',
    'agent-transport.conf.template': '875a3667a5c5b9ea9f4bc4bb20b4d2c373d186e72fd6ce77e3ffbd9123740cdc',
    'camera-publisher-transport.conf.template': '1f12ad065ad16a31b765098ac2c83fc85e36e3250f9944128f8554a107519543',
}
UNIT_PINS = {
    'edge': 'fbfcc732e86ecee25d2ec98e802f6735fc5701b226d2ee58b810998c78898dd7',
    'camera': 'c604a65a072f9cc83d1ebe0d08c72f8f95c7faf12148fd64f99c2c0dc0c42e51',
}
AGENT_CHANGES = {'thirdhand_edge/' + name for name in ('media_upload.py', 'media_publisher.py', 'upload.py', 'runtime.py')}
CAMERA_CHANGES = {'thirdhand_edge/' + name for name in ('media_upload.py', 'media_publisher.py', 'camera_runtime.py')}
now = time.time


class InstallError(Exception):
    def __init__(self, code, rollback=None):
        super().__init__(code)
        self.code, self.rollback = code, rollback


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def pretty(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def require_identity():
    if (sys.platform != 'linux' or fcntl is None or sys.version_info < (3, 11)
            or os.getuid() != 1000 or os.geteuid() != 1000):
        raise InstallError('UBUNTU_UID1000_PYTHON311_REQUIRED')


def safe_path(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path or path.is_symlink():
        raise InstallError('UNSAFE_PATH')
    return path


def regular(path, maximum=2 * 1024 * 1024):
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise InstallError('REGULAR_BOUNDED_FILE_REQUIRED')
    return path.read_bytes()


def read_archive(raw, role, before):
    entries, total = {}, 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            for item in archive:
                parts = PurePosixPath(item.name).parts
                allowed = item.name == 'source-manifest.json' or (
                    len(parts) == 2 and parts[0] == 'thirdhand_edge'
                    and re.fullmatch(r'[A-Za-z0-9_]+\.py', parts[1]))
                total += item.size
                if (not item.isfile() or not allowed or '\\' in item.name or item.name in entries
                        or item.size < 0 or item.size > 262144 or total > 2 * 1024 * 1024):
                    raise InstallError('UNSAFE_ARCHIVE')
                entries[item.name] = archive.extractfile(item).read()
        manifest = json.loads(entries['source-manifest.json'])
        files = {name: value for name, value in entries.items() if name != 'source-manifest.json'}
        hashes = {name: sha(value) for name, value in files.items()}
        permitted = AGENT_CHANGES if role == 'agent' else CAMERA_CHANGES
        if (len(files) != 20 or set(files) != set(before) or manifest['files'] != hashes
                or manifest['baselineFiles'] != before or manifest['automaticSdkConnect'] is not False
                or manifest['role'] != role + '-transport-candidate'
                or set(manifest['changedFiles']) != permitted
                or {name for name in files if hashes[name] != before[name]} != permitted):
            raise InstallError('ARCHIVE_MANIFEST_MISMATCH')
        for name, value in files.items():
            compile(value, name, 'exec', dont_inherit=True)
        return entries
    except InstallError:
        raise
    except Exception:
        raise InstallError('ARCHIVE_INVALID') from None


def roles():
    return {
        'edge': {'old': OLD_AGENT, 'new': NEW_AGENT, 'dropin': USER_DROPIN,
                 'fragment': USER_UNIT_FILE, 'unit': EDGE_UNIT, 'source': 'agent'},
        'camera': {'old': OLD_CAMERA, 'new': NEW_CAMERA, 'dropin': SYSTEM_DROPIN,
                   'fragment': SYSTEM_UNIT_FILE, 'unit': CAMERA_UNIT, 'source': 'camera'},
    }


def load_candidate():
    blobs = {}
    for name, expected in PINS.items():
        value = regular(CANDIDATE / name)
        if sha(value) != expected:
            raise InstallError('CANDIDATE_DIGEST_MISMATCH')
        blobs[name] = value
    summary = json.loads(regular(CANDIDATE / 'candidate-summary.json'))
    digest = summary.pop('candidateDigest', None)
    if digest != CANDIDATE_DIGEST or sha(canonical(summary)) != CANDIDATE_DIGEST:
        raise InstallError('CANDIDATE_ID_MISMATCH')
    if any(summary['artifacts'][name]['sha256'] != expected for name, expected in PINS.items()):
        raise InstallError('CANDIDATE_INDEX_MISMATCH')
    before = json.loads(blobs['baseline-public.json'])
    templates = {'edge': blobs['agent-transport.conf.template'],
                 'camera': blobs['camera-publisher-transport.conf.template']}
    sources = {}
    for role, item in roles().items():
        source = item['source']
        if (before[source]['source'] != item['old'].as_posix()
                or summary[source]['newSource'] != item['new'].as_posix()
                or templates[role] != ('[Service]\nEnvironment=PYTHONPATH=' + item['new'].as_posix() + '\n').encode()):
            raise InstallError('FIXED_TARGET_MISMATCH')
        entries = read_archive(blobs[source + '.source.tar.gz'], source, before[source]['files'])
        if (sha(entries['source-manifest.json']) != summary[source]['manifestSha256']
                or json.loads(entries['source-manifest.json'])['files'] != summary[source]['files']):
            raise InstallError('SOURCE_INDEX_MISMATCH')
        sources[role] = entries
    return {'templates': templates, 'sources': sources, 'before': before,
            'baselineRaw': blobs['baseline-public.json']}


def load_rollback_payload():
    # Recovery depends on the pinned old-source receipt, not the new source or
    # incoming package that may be the reason recovery is needed.
    raw = regular(REVIEW / 'baseline-public.json')
    if sha(raw) != PINS['baseline-public.json']:
        raise InstallError('BEFORE_BACKUP_CHANGED')
    before = json.loads(raw)
    templates = {}
    for role, item in roles().items():
        if before[item['source']]['source'] != item['old'].as_posix():
            raise InstallError('FIXED_TARGET_MISMATCH')
        templates[role] = ('[Service]\nEnvironment=PYTHONPATH=' + item['new'].as_posix() + '\n').encode()
        pin = 'agent-transport.conf.template' if role == 'edge' else 'camera-publisher-transport.conf.template'
        if sha(templates[role]) != PINS[pin]:
            raise InstallError('FIXED_TEMPLATE_MISMATCH')
    return {'templates': templates, 'before': before, 'baselineRaw': raw}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise InstallError('ROBOT_STATUS_UNAVAILABLE')


def robot_state():
    try:
        info = TOKEN_FILE.stat()
        if os.name == 'posix' and (info.st_uid != 1000 or info.st_mode & 0o077):
            raise InstallError('ROBOT_STATUS_UNAVAILABLE')
        token = regular(TOKEN_FILE, 128).decode('ascii').strip()
        if not re.fullmatch(r'[a-f0-9]{64}', token):
            raise InstallError('ROBOT_STATUS_UNAVAILABLE')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        def get(path, headers=None):
            request = urllib.request.Request('http://127.0.0.1:3000' + path, headers=headers or {})
            with opener.open(request, timeout=3) as response:
                raw = response.read(65537)
                if len(raw) > 65536 or response.headers.get_content_type() != 'application/json':
                    raise InstallError('ROBOT_STATUS_UNAVAILABLE')
                return json.loads(raw)
        context = get('/edge-control/v1/context', {'X-ThirdHand-Edge-Token': token})
        health = get('/health')
        if context.get('deviceId') != DEVICE_ID or health.get('mode') != 'hardware':
            raise InstallError('ROBOT_STATUS_UNAVAILABLE')
        return {'sdkConnected': context.get('sdkConnected'), 'readOnly': context.get('readOnly'),
                'connected': health['robot'].get('connected'), 'moving': health['robot'].get('moving')}
    except InstallError:
        raise
    except Exception:
        raise InstallError('ROBOT_STATUS_UNAVAILABLE') from None


def assert_robot_disconnected():
    value = robot_state()
    if (value.get('sdkConnected') is not False or value.get('readOnly') is not True
            or value.get('connected', False) is not False or value.get('moving') is not False):
        raise InstallError('ROBOT_STATE_NOT_DISCONNECTED')
    return value


def run(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode:
        raise InstallError('SERVICE_COMMAND_FAILED')
    return result.stdout


def inspect_unit(role):
    item = roles()[role]
    command = ['systemctl'] + (['--user'] if role == 'edge' else [])
    raw = run(command + ['show', item['unit'], '-p', 'FragmentPath', '-p', 'DropInPaths',
                         '-p', 'Environment', '-p', 'ActiveState', '--no-pager'])
    values = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    environment = dict(entry.split('=', 1) for entry in shlex.split(values.get('Environment', '')) if '=' in entry)
    return {'FragmentPath': values.get('FragmentPath'), 'DropInPaths': shlex.split(values.get('DropInPaths', '')),
            'pythonPath': environment.get('PYTHONPATH'), 'ActiveState': values.get('ActiveState')}


def verify_source(directory, expected):
    safe_path(directory)
    actual = {path.relative_to(directory).as_posix(): sha(regular(path))
              for path in (directory / 'thirdhand_edge').glob('*.py')}
    if actual != expected:
        raise InstallError('SOURCE_CHANGED')


def verify_new_source(directory, entries):
    safe_path(directory)
    leaves = {path.relative_to(directory).as_posix() for path in directory.rglob('*') if path.is_file()}
    if leaves != set(entries) or any(regular(directory / name) != raw for name, raw in entries.items()):
        raise InstallError('NEW_SOURCE_CHANGED')


def cloud_review(path, expected_sha, rollback=False):
    try:
        if not path or not expected_sha or not re.fullmatch(r'[a-fA-F0-9]{64}', expected_sha):
            raise InstallError('FRESH_CLOUD_REVIEW_REQUIRED')
        path = Path(path)
        raw = regular(path, 16384)
        info = path.stat()
        if os.name == 'posix' and (info.st_uid != 1000 or info.st_mode & 0o077):
            raise InstallError('CLOUD_REVIEW_PRIVATE_FILE_REQUIRED')
        if sha(raw) != expected_sha.lower():
            raise InstallError('CLOUD_REVIEW_DIGEST_MISMATCH')
        value = json.loads(raw)
        checked = datetime.fromisoformat(value['checkedAt'].replace('Z', '+00:00'))
        if checked.tzinfo is None or not -5 <= now() - checked.timestamp() <= 60:
            raise InstallError('CLOUD_REVIEW_STALE')
        allowed = {NEW_CLOUD, OLD_CLOUD} if rollback else {NEW_CLOUD}
        if (value.get('verified') is not True or value.get('currentRelease') not in allowed
                or value.get('deviceId') != DEVICE_ID or type(value.get('activeLeases')) is not int
                or value['activeLeases'] != 0):
            raise InstallError('CLOUD_REVIEW_NOT_CLEAR')
        return value
    except InstallError:
        raise
    except Exception:
        raise InstallError('CLOUD_REVIEW_INVALID') from None


def check_dropin_directories(payload):
    # systemctl show only reports loaded configuration. Reject foreign on-disk
    # .conf entries as well, including changes not followed by daemon-reload.
    for role, item in roles().items():
        directory = safe_path(item['dropin'].parent)
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise InstallError('DROPIN_DIRECTORY_CHANGED')
        for path in directory.iterdir():
            if not path.name.endswith('.conf'):
                continue
            if path != item['dropin']:
                raise InstallError('UNKNOWN_DISK_DROPIN')
            if regular(path) != payload['templates'][role]:
                raise InstallError('OWNED_DROPIN_CHANGED')


def review(payload, cloud_file=None, cloud_sha=None):
    require_identity()
    state = assert_robot_disconnected()
    check_dropin_directories(payload)
    units, installed, fragments = {}, [], {}
    for role, item in roles().items():
        verify_source(item['old'], payload['before'][item['source']]['files'])
        fragments[role] = sha(regular(item['fragment']))
        if fragments[role] != UNIT_PINS[role]:
            raise InstallError('UNIT_CHANGED')
        present = item['dropin'].exists() or item['dropin'].is_symlink()
        if present and regular(item['dropin']) != payload['templates'][role]:
            raise InstallError('OWNED_DROPIN_CHANGED')
        if present:
            verify_new_source(item['new'], payload['sources'][role]); installed.append(role)
        unit = inspect_unit(role)
        expected_drops = [str(item['dropin'])] if present else []
        if (unit['FragmentPath'] != str(item['fragment']) or unit['DropInPaths'] != expected_drops
                or unit['pythonPath'] != str(item['new'] if present else item['old'])
                or unit['ActiveState'] not in ({'active', 'activating'} if role == 'camera' else {'active'})):
            raise InstallError('UNIT_CHANGED')
        units[role] = unit
    if cloud_file or cloud_sha:
        cloud_review(cloud_file, cloud_sha)
    return {'mode': 'review', 'candidateDigest': CANDIDATE_DIGEST, 'sdkConnected': state['sdkConnected'],
            'readOnly': state['readOnly'], 'cloudReview': 'verifiedFresh' if cloud_file else 'pending',
            'installedDropins': installed, 'units': units, 'fragmentSha256': fragments,
            'newSourceFilesPerRole': 21, 'sdkActions': 0, 'motionCommands': 0}


def install_source(directory, entries):
    safe_path(directory)
    if directory.exists():
        verify_new_source(directory, entries)
        return
    directory.mkdir(mode=0o700)
    (directory / 'thirdhand_edge').mkdir(mode=0o700)
    for name, raw in entries.items():
        path = directory / name
        with path.open('xb') as stream:
            stream.write(raw)
        path.chmod(0o400)
    (directory / 'thirdhand_edge').chmod(0o500)
    directory.chmod(0o500)
    verify_new_source(directory, entries)


@contextlib.contextmanager
def installation_lock():
    with (REVIEW / 'installer.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise InstallError('INSTALLER_BUSY') from None
        yield


def prepare_backup(before, payload):
    safe_path(REVIEW)
    REVIEW.mkdir(mode=0o700, parents=True, exist_ok=True)
    value = {'format': 1, 'candidateDigest': CANDIDATE_DIGEST, 'originalDropinsAbsent': True,
             'fragmentSha256': before['fragmentSha256']}
    path = REVIEW / 'before-public.json'
    if path.exists():
        if json.loads(regular(path)) != value:
            raise InstallError('BEFORE_BACKUP_CHANGED')
    else:
        with path.open('xb') as stream:
            stream.write(pretty(value))
        path.chmod(0o600)
    baseline = REVIEW / 'baseline-public.json'
    if baseline.exists():
        if regular(baseline) != payload['baselineRaw']:
            raise InstallError('BEFORE_BACKUP_CHANGED')
    else:
        with baseline.open('xb') as stream:
            stream.write(payload['baselineRaw'])
        baseline.chmod(0o600)


def restart(role, checkpoint=None):
    if role == 'edge':
        run(['systemctl', '--user', 'daemon-reload'])
        if checkpoint:
            checkpoint()
        run(['systemctl', '--user', 'restart', EDGE_UNIT])
    else:
        run(['sudo', '-n', 'systemctl', 'daemon-reload'])
        if checkpoint:
            checkpoint()
        run(['sudo', '-n', 'systemctl', 'restart', CAMERA_UNIT])


def write_dropin(role, raw):
    item = roles()[role]
    safe_path(item['dropin'])
    if item['dropin'].exists():
        raise InstallError('DROPIN_ALREADY_EXISTS')
    if role == 'edge':
        item['dropin'].parent.mkdir(mode=0o700, exist_ok=True)
        with item['dropin'].open('xb') as stream:
            stream.write(raw)
        item['dropin'].chmod(0o600)
    else:
        stage = REVIEW / 'camera-publisher-transport.conf'
        if stage.exists() and regular(stage) != raw:
            raise InstallError('STAGED_DROPIN_CHANGED')
        if not stage.exists():
            with stage.open('xb') as stream:
                stream.write(raw)
            stage.chmod(0o600)
        run(['sudo', '-n', 'install', '-d', '-o', 'root', '-g', 'root', '-m', '755', str(item['dropin'].parent)])
        run(['sudo', '-n', 'install', '-o', 'root', '-g', 'root', '-m', '644', str(stage), str(item['dropin'])])
    if regular(item['dropin']) != raw:
        raise InstallError('DROPIN_WRITE_UNCONFIRMED')


def wait_units(expected):
    for attempt in range(30):
        assert_robot_disconnected()
        if all(inspect_unit(role)['ActiveState'] == 'active' and inspect_unit(role)['pythonPath'] == str(path)
               for role, path in expected.items()):
            return
        if attempt < 29:
            time.sleep(0.25)
    raise InstallError('SERVICE_HEALTH_UNCONFIRMED')


def rollback(payload, cloud_file, cloud_sha):
    require_identity()
    def checkpoint():
        try:
            check_dropin_directories(payload)
            assert_robot_disconnected()
            cloud_review(cloud_file, cloud_sha, rollback=True)
        except InstallError as error:
            error.rollback = 'blocked'
            raise
    checkpoint()
    backup = json.loads(regular(REVIEW / 'before-public.json'))
    if backup.get('candidateDigest') != CANDIDATE_DIGEST or backup.get('originalDropinsAbsent') is not True:
        raise InstallError('BEFORE_BACKUP_CHANGED')
    found = []
    for role, item in roles().items():
        verify_source(item['old'], payload['before'][item['source']]['files'])
        if sha(regular(item['fragment'])) != backup['fragmentSha256'][role] or backup['fragmentSha256'][role] != UNIT_PINS[role]:
            raise InstallError('UNIT_CHANGED')
        unit = inspect_unit(role)
        if (unit['FragmentPath'] != str(item['fragment'])
                or any(path != str(item['dropin']) for path in unit['DropInPaths'])
                or unit['pythonPath'] not in {str(item['old']), str(item['new'])}):
            raise InstallError('UNIT_CHANGED')
        if item['dropin'].exists() or item['dropin'].is_symlink():
            if regular(item['dropin']) != payload['templates'][role]:
                raise InstallError('OWNED_DROPIN_CHANGED')
            found.append(role)
    for role in found:
        checkpoint()
        path = roles()[role]['dropin']
        if role == 'edge':
            path.unlink()
        else:
            run(['sudo', '-n', 'rm', '--', str(path)])
    # A previous recovery may have reloaded the old configuration but stopped
    # before restarting its process. Re-establish both fixed old processes;
    # configured PYTHONPATH does not prove the running process has changed.
    for role in roles():
        checkpoint()
        restart(role, checkpoint=checkpoint)
    wait_units({role: item['old'] for role, item in roles().items()})
    checkpoint()
    return {'rolledBack': True, 'withdrawnDropins': found, 'snapshotsAndStateRetained': True,
            'sdkActions': 0, 'motionCommands': 0}


def apply(payload, cloud_file, cloud_sha):
    cloud_review(cloud_file, cloud_sha)
    before = review(payload, cloud_file, cloud_sha)
    if len(before['installedDropins']) == 2:
        return {'applied': True, 'alreadyApplied': True, 'sdkActions': 0, 'motionCommands': 0}
    if before['installedDropins']:
        raise InstallError('PARTIAL_INSTALL_REQUIRES_ROLLBACK')
    prepare_backup(before, payload)
    with installation_lock():
        # Recheck inside the lock, before any source or unit change.
        locked_before = review(payload, cloud_file, cloud_sha)
        if len(locked_before['installedDropins']) == 2:
            return {'applied': True, 'alreadyApplied': True, 'sdkActions': 0, 'motionCommands': 0}
        if locked_before['installedDropins']:
            raise InstallError('PARTIAL_INSTALL_REQUIRES_ROLLBACK')
        touched = False
        def checkpoint():
            check_dropin_directories(payload)
            assert_robot_disconnected()
            cloud_review(cloud_file, cloud_sha)
        try:
            for role, item in roles().items():
                install_source(item['new'], payload['sources'][role])
            for role in ('edge', 'camera'):
                checkpoint()
                touched = True
                write_dropin(role, payload['templates'][role])
                checkpoint()
                restart(role, checkpoint=checkpoint)
                assert_robot_disconnected()
            wait_units({role: item['new'] for role, item in roles().items()})
            final = review(payload, cloud_file, cloud_sha)
            if len(final['installedDropins']) != 2:
                raise InstallError('INSTALLATION_UNCONFIRMED')
        except BaseException as error:
            code = error.code if isinstance(error, InstallError) else 'APPLICATION_FAILED'
            outcome = 'not-needed'
            if touched:
                try:
                    rollback(payload, cloud_file, cloud_sha)
                    outcome = 'restored'
                except Exception:
                    outcome = 'blocked'
            raise InstallError(code, rollback=outcome) from None
    return {'applied': True, 'candidateDigest': CANDIDATE_DIGEST, 'changedUnits': [EDGE_UNIT, CAMERA_UNIT],
            'robotServiceUnchanged': True, 'sdkActions': 0, 'motionCommands': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--apply', action='store_true')
    modes.add_argument('--rollback', action='store_true')
    parser.add_argument('--cloud-review-file', type=Path)
    parser.add_argument('--cloud-review-sha256')
    args = parser.parse_args(argv)
    try:
        require_identity()
        if args.rollback:
            # apply already owns this lock when it invokes its internal rollback.
            # Explicit recovery must take the same lock before reading its backup.
            with installation_lock():
                result = rollback(load_rollback_payload(), args.cloud_review_file, args.cloud_review_sha256)
        else:
            payload = load_candidate()
            result = (apply if args.apply else review)(payload, args.cloud_review_file, args.cloud_review_sha256)
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        report = {'applied': False, 'code': error.code if isinstance(error, InstallError) else 'REVIEW_FAILED'}
        if isinstance(error, InstallError) and error.rollback:
            report['rollback'] = error.rollback
        print(json.dumps(report, sort_keys=True))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
