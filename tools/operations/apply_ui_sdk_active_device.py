"""C8 correction: create new snapshots; never overwrite the active C3c/C3e trees.

Default is read-only review. Apply/rollback require both services stopped and
fresh operator-collected cloud/robot clearance. Service reload/start is separate.
"""
import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import time

HOME = Path.home()
BASE = HOME / '.local/share/thirdhand-stage-device/20261031'
ROOT = BASE.parent / 'C8-active-state-20261101'
UNITS = HOME / '.config/systemd/user'
PINS_SHA = '103171b62779c34408845549dc68fe8be7aee0b7b8b83e8be5bf18ae729a34fa'
EDGE = 'thirdhand-stage-edge-read-only.service'
ROBOT = 'thirdhand-tcp-calibration-robot.service'
DEVICE = 'ee625a57-049a-4c5d-92e1-9578ab9d21c3'


def require(ok, code):
    if not ok:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe(path):
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'UNSAFE_PATH')
    return path


def read(path, limit=2_000_000):
    safe(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, 'INVALID_FILE')
    return path.read_bytes()


def relative(name):
    p = PurePosixPath(name)
    require(not p.is_absolute() and p.as_posix() == name and not any(x in ('.', '..') for x in p.parts)
            and '\\' not in name and ':' not in name, 'INVALID_RELATIVE_PATH')
    return name


def inventory(root):
    safe(root)
    result = {}
    for p in root.rglob('*'):
        safe(p)
        if '__pycache__' in p.parts:
            continue
        if p.is_file():
            result[p.relative_to(root).as_posix()] = sha(read(p))
        else:
            require(p.is_dir(), 'SPECIAL_SOURCE_FILE')
    return result


def load():
    raw = read(ROOT / 'active-pins.json')
    require(sha(raw) == PINS_SHA, 'PINS_CHANGED')
    pins = json.loads(raw)
    for group in pins['snapshots']:
        require('/' not in relative(group['old']) and '/' not in relative(group['new']), 'INVALID_ROOT')
        for name in group['after']:
            relative(name)
    return pins


def system_show(unit, key):
    return subprocess.run(['systemctl', '--user', 'show', unit, '-p', key, '--value'],
                          check=True, capture_output=True, text=True).stdout.strip()


def inactive():
    for unit in (EDGE, ROBOT):
        require(system_show(unit, 'ActiveState') in ('inactive', 'failed'), 'SERVICES_MUST_BE_STOPPED')


def unit_checks(pins, allow_new=False):
    for name, expected in pins['unitHashes'].items():
        require(sha(read(UNITS / relative(name))) == expected, 'UNIT_CHANGED')
    for unit in (EDGE, ROBOT):
        actual = {p.relative_to(UNITS).as_posix() for p in (UNITS / (unit + '.d')).glob('*.conf')}
        expected = {n for n in pins['unitHashes'] if n.startswith(unit + '.d/')}
        if allow_new:
            expected |= {n for n in pins['dropins'] if n.startswith(unit + '.d/') and (UNITS / n).exists()}
        require(actual == expected, 'UNEXPECTED_DROPIN')


def clearance(path):
    raw = read(path, 4096)
    info = path.stat()
    if os.name == 'posix':
        require(info.st_uid == os.getuid() and not info.st_mode & 0o077, 'PRIVATE_CLEARANCE_REQUIRED')
    v = json.loads(raw)
    require(v.get('schema') == 1 and v.get('phase') == 'C8-active-state' and v.get('deviceId') == DEVICE
            and type(v.get('checkedAt')) is int and -1000 <= time.time()*1000-v['checkedAt'] <= 60000
            and type(v.get('activeLeases')) is int and v['activeLeases'] == 0
            and type(v.get('activeCommands')) is int and v['activeCommands'] == 0
            and v.get('sdkConnected') is False and v.get('moving') is False
            and v.get('readOnly') is True and v.get('recordingHealthy') is True, 'CLEARANCE_REQUIRED')


def contents(pins):
    raw = read(ROOT / 'device.delta.json.gz')
    require(sha(raw) == pins['packageSha256'], 'PACKAGE_CHANGED')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as z:
        decoded = z.read(2_000_001)
    require(len(decoded) <= 2_000_000, 'PACKAGE_TOO_LARGE')
    value = json.loads(decoded)
    require(set(value['changes']) == set(pins['changes']), 'PACKAGE_SCOPE_CHANGED')
    result = {n: base64.b64decode(v, validate=True) for n, v in value['changes'].items()}
    require({n: sha(v) for n, v in result.items()} == pins['changes'], 'CONTENT_CHANGED')
    return result


def exclusive(path, raw):
    safe(path)
    with path.open('xb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())


def dropin_bytes(template):
    return template.replace('@HOME@', HOME.as_posix()).encode()


def restore_dropins(pins):
    # Only remove our exact additions; never replace a concurrent modification.
    unit_checks(pins, allow_new=True)
    for name, template in pins['dropins'].items():
        path = safe(UNITS / name)
        require(not path.exists() or read(path) == dropin_bytes(template), 'ROLLBACK_DROPIN_CHANGED')
    for name in pins['dropins']:
        path = UNITS / name
        if path.exists():
            path.unlink()


def execute(apply=False, rollback=False, clearance_path=None):
    require(not (apply and rollback), 'INVALID_MODE')
    pins = load()
    for group in pins['snapshots']:
        require(inventory(BASE / group['old']) == group['before'], 'ACTIVE_SNAPSHOT_CHANGED')
    if rollback:
        inactive(); clearance(clearance_path)
        receipt = json.loads(read(ROOT / 'applied.json'))
        require(receipt.get('pinsSha256') == PINS_SHA, 'RECEIPT_CHANGED')
        restore_dropins(pins)
        return {'rolledBack': True, 'requiresDaemonReload': True, 'servicesStarted': False}
    unit_checks(pins)
    for unit in (EDGE, ROBOT):
        require(system_show(unit, 'NeedDaemonReload') == 'no', 'UNLOADED_UNIT_CHANGE')
    # Check effective source selection, not just dormant source-file hashes.
    require('PYTHONPATH=' + str(BASE / pins['snapshots'][0]['old']) in system_show(EDGE, 'Environment').split(),
            'ACTIVE_AGENT_PATH_CHANGED')
    require(str(BASE / pins['snapshots'][1]['old'] / 'services/robot/src/server.js') + ' ' in
            system_show(ROBOT, 'ExecStart'), 'ACTIVE_ROBOT_PATH_CHANGED')
    changed = contents(pins)
    for group in pins['snapshots']:
        require(not safe(BASE / group['new']).exists(), 'NEW_SNAPSHOT_EXISTS')
    require(not (ROOT / 'applied.json').exists(), 'RECEIPT_EXISTS')
    if not apply:
        return {'applied': False, 'newSnapshots': [g['new'] for g in pins['snapshots']],
                'sourceChanges': len(changed), 'dropins': sorted(pins['dropins']), 'sdkCommands': 0}
    inactive(); clearance(clearance_path)
    # No source roots are modified or recursively deleted, even on failure.
    for group in pins['snapshots']:
        target = BASE / group['new']
        target.mkdir(mode=0o700)
        for name, expected in group['after'].items():
            key = group['old'] + '/' + name
            raw = changed[key] if key in changed else read(BASE / key)
            require(sha(raw) == expected, 'SOURCE_RACE')
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            exclusive(path, raw)
        require(inventory(target) == group['after'], 'NEW_SNAPSHOT_INVALID')
    inactive(); clearance(clearance_path); unit_checks(pins)
    for group in pins['snapshots']:
        require(inventory(BASE / group['old']) == group['before'], 'ACTIVE_SNAPSHOT_CHANGED')
    exclusive(ROOT / 'applied.json', json.dumps({'pinsSha256': PINS_SHA}).encode())
    try:
        for name, template in pins['dropins'].items():
            inactive(); clearance(clearance_path)
            exclusive(UNITS / name, dropin_bytes(template))
    except BaseException:
        restore_dropins(pins)
        raise
    return {'applied': True, 'sdkCommands': 0, 'requiresDaemonReload': True, 'servicesStarted': False}


if __name__ == '__main__':
    require(os.name == 'posix' and os.getuid() == 1000, 'EXPECTED_LINUX_USER_REQUIRED')
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true')
    parser.add_argument('--clearance', type=Path)
    args = parser.parse_args()
    if args.apply or args.rollback:
        require(args.clearance is not None, 'CLEARANCE_REQUIRED')
        import fcntl
        # Match the existing cooperative SDK/CAN lock; no device is opened.
        fd = os.open('/tmp/thirdhand-robot-can0.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1,
                    'INVALID_COOPERATIVE_LOCK')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(execute(args.apply, args.rollback, args.clearance), sort_keys=True))
        finally:
            os.close(fd)
    else:
        print(json.dumps(execute(), sort_keys=True))
