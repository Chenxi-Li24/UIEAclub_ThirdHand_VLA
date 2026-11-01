"""C8b five-file offline installer; review by default, never sends SDK commands.

Apply/rollback require both existing user services to be stopped by the reviewed
deployment sequence. Credentials, original checkout and SDK are never touched.
"""
import argparse
import base64
import gzip
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess

BASE = Path.home() / '.local/share/thirdhand-stage-device/20261031'
ROOT = BASE.parent / 'C8-ui-sdk-20261101'
PACKAGE_SHA = '12ac8cf0773393aa4c36e6792f4944e617420b58afb7730b500cd8f06918815d'
AGENT = 'agent-source/thirdhand_edge/'
ROBOT = 'robot/services/robot/src/'
BEFORE = {
    AGENT + 'runtime.py': '00d92659932fd0c1b4ede4732384a43815c2f900e978fad58c32d7a6f4b5a340',
    AGENT + 'telemetry.py': 'ba16dab3ab6371c860bac284386be0fff7bc7969e454ec34f96befcd6ebc3832',
    ROBOT + 'remote-gateway.js': '15a5eeb794cba2c1efdfdf7489ae234b7dbce47efac61765b544dae86d56baf8',
    AGENT + 'latest_state.py': None, AGENT + 'state_upload.py': None,
}
PROTECTED = {
    AGENT + 'upload.py': '2e8fa8645c6f966e6570fbcad681b2f206eca204e8ee584b5ebf1e677a3d8652',
    ROBOT + 'robot-controller.js': '2cbeafe497b30b7a8effecde3e59dae6c472d30dd77b7785c3988eac43b696da',
    ROBOT + 'startouch_bridge.py': '126a8055544c04207d190dff0da31c0ba3407799ffcaa9d7803b3bcab08b2d3d',
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe(path):
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'UNSAFE_PATH')
    return path


def read(path):
    safe(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= 2_000_000, 'INVALID_FILE')
    return path.read_bytes()


def check(mapping):
    for name, expected in mapping.items():
        path = safe(BASE / name)
        require((not path.exists()) if expected is None else sha(read(path)) == expected, 'SOURCE_CHANGED: ' + name)


def package():
    raw = read(ROOT / 'device.delta.json.gz')
    require(sha(raw) == PACKAGE_SHA, 'PACKAGE_DIGEST_MISMATCH')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded = stream.read(2_000_001)
    require(len(decoded) <= 2_000_000, 'PACKAGE_TOO_LARGE')
    value = json.loads(decoded)
    require(value.get('format') == 1 and value.get('beforeHashes') == BEFORE
            and value.get('protectedHashes') == PROTECTED and set(value.get('changes', {})) == set(BEFORE)
            and set(value.get('afterHashes', {})) == set(BEFORE), 'PACKAGE_SCOPE_MISMATCH')
    contents = {n: base64.b64decode(v, validate=True) for n, v in value['changes'].items()}
    require(all(sha(v) == value['afterHashes'][n] for n, v in contents.items()), 'PACKAGE_CONTENT_MISMATCH')
    return contents, value['afterHashes']


def inactive():
    for unit in ('thirdhand-stage-edge-read-only.service', 'thirdhand-tcp-calibration-robot.service'):
        state = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'ActiveState', '--value'],
                               capture_output=True, text=True, check=True).stdout.strip()
        require(state in ('inactive', 'failed'), 'SERVICE_MUST_BE_STOPPED: ' + unit)


def write(path, raw):
    safe(path)
    temporary = path.with_name(path.name + '.C8-tmp')
    safe(temporary)
    created = False
    try:
        with temporary.open('xb') as stream:
            created = True
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o644)
        temporary.replace(path)
    finally:
        if created and temporary.exists():
            safe(temporary).unlink()


def restore(after):
    # Restore pinned backups even if the upload package is lost or corrupted.
    for name, before in BEFORE.items():
        path = safe(BASE / name)
        current = sha(read(path)) if path.exists() else None
        require(current in (before, after[name]), 'ROLLBACK_SOURCE_CHANGED: ' + name)
        if before is not None:
            require(sha(read(ROOT / 'before' / name)) == before, 'BACKUP_CHANGED')
    for name, before in BEFORE.items():
        path = BASE / name
        if before is None:
            if path.exists():
                path.unlink()
        else:
            write(path, read(ROOT / 'before' / name))
    check(BEFORE)


def execute(apply=False, rollback=False):
    require(not (apply and rollback), 'INVALID_MODE')
    safe(BASE); safe(ROOT)
    check(PROTECTED)
    if rollback:
        inactive()
        receipt = json.loads(read(ROOT / 'before.json'))
        require(receipt.get('beforeHashes') == BEFORE and set(receipt.get('afterHashes', {})) == set(BEFORE), 'INVALID_RECEIPT')
        restore(receipt['afterHashes'])
        return {'rolledBack': True, 'sdkCommands': 0, 'servicesStarted': False}
    contents, after = package()
    check(BEFORE)
    if not apply:
        return {'applied': False, 'files': sorted(contents), 'sdkCommands': 0, 'protectedFiles': sorted(PROTECTED)}
    inactive()
    require(not (ROOT / 'before.json').exists(), 'BACKUP_ALREADY_EXISTS')
    for name, before in BEFORE.items():
        if before is not None:
            target = ROOT / 'before' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            safe(target)
            with target.open('xb') as stream:
                stream.write(read(BASE / name))
    receipt = {'beforeHashes': BEFORE, 'afterHashes': after}
    with (ROOT / 'before.json').open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, sort_keys=True)
    check(BEFORE); check(PROTECTED); inactive()
    try:
        for name, raw in contents.items():
            write(BASE / name, raw)
        check(after); check(PROTECTED)
    except BaseException:
        restore(after)
        raise
    return {'applied': True, 'files': sorted(contents), 'sdkCommands': 0, 'servicesStarted': False}


if __name__ == '__main__':
    require(os.name == 'posix' and getpass.getuser() == 'nieqingcao', 'EXPECTED_LINUX_USER_REQUIRED')
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if args.apply or args.rollback:
        import fcntl
        with safe(ROOT / 'installer.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(execute(args.apply, args.rollback), sort_keys=True))
    else:
        print(json.dumps(execute(), sort_keys=True))
