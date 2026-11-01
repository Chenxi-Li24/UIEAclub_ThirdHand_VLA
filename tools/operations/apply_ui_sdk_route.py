"""Pinned C8 state route; review by default. No ports, certificate or SDK changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

CONFIG = Path('/etc/nginx/sites-available/edge.uiea-thirdhand.com')
ROOT = Path('/var/backups/thirdhand/access-C8b-state-route-20261101')
BEFORE = 'a2e7dff2bc075998e1898de8137b0a3386ae828e0a11bf4bfe28412d7663f44a'
AFTER = '0b65801a9933e1ad1e3b7f4dbaa69b94b63d9e72032e7ae094b5214e6ed32c68'
BLOCK_SHA = 'af9834e79eed184d6bb551d399a4f009967761850f6f79fb193bf754e511b531'
ANCHOR = b'location = /edge/v1/telemetry-batches {'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe(path):
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'UNSAFE_PATH')
    return path


def read(path):
    safe(path)
    require(path.is_file() and path.stat().st_size <= 100_000, 'INVALID_FILE')
    return path.read_bytes()


def candidate(raw, block):
    require(sha(raw) == BEFORE, 'CONFIG_CHANGED')
    require(sha(block) == BLOCK_SHA, 'BLOCK_CHANGED')
    require(raw.count(ANCHOR) == 1 and b'location = /edge/v1/state {' not in raw, 'INVALID_ANCHOR')
    updated = raw.replace(ANCHOR, block + ANCHOR, 1)
    require(sha(updated) == AFTER, 'CANDIDATE_CHANGED')
    return updated


def replace(raw):
    safe(CONFIG)
    mode = CONFIG.stat().st_mode & 0o777
    temporary = safe(CONFIG.with_name(CONFIG.name + '.C8-tmp'))
    created = False
    try:
        with temporary.open('xb') as stream:
            created = True
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        temporary.replace(CONFIG)
    finally:
        if created and temporary.exists():
            temporary.unlink()


def validate_reload():
    subprocess.run(['nginx', '-t'], check=True, capture_output=True)
    subprocess.run(['systemctl', 'reload', 'nginx'], check=True, capture_output=True)


def execute(apply=False, rollback=False):
    require(not (apply and rollback), 'INVALID_MODE')
    safe(ROOT)
    raw = read(CONFIG)
    backup = safe(ROOT / 'edge.before.conf')
    if rollback:
        require(sha(raw) == AFTER, 'ROLLBACK_CONFIG_CHANGED')
        old = read(backup)
        require(sha(old) == BEFORE, 'BACKUP_CHANGED')
        replace(old)
        validate_reload()
        return {'rolledBack': True, 'sha256': BEFORE}
    updated = candidate(raw, read(ROOT / 'state-location.conf'))
    if not apply:
        return {'applied': False, 'beforeSha256': BEFORE, 'afterSha256': AFTER, 'newPorts': []}
    require(not backup.exists(), 'BACKUP_ALREADY_EXISTS')
    with backup.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(sha(read(CONFIG)) == BEFORE, 'CONFIG_CHANGED')
    try:
        replace(updated)
        validate_reload()
    except BaseException:
        # Do not overwrite a concurrent administrator edit during recovery.
        require(sha(read(CONFIG)) in (BEFORE, AFTER), 'RECOVERY_CONFIG_CHANGED')
        replace(raw)
        validate_reload()
        raise
    return {'applied': True, 'sha256': sha(read(CONFIG)), 'newPorts': []}


if __name__ == '__main__':
    require(os.name == 'posix' and os.geteuid() == 0, 'ROOT_ON_LINUX_REQUIRED')
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true')
    group.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if args.apply or args.rollback:
        import fcntl
        with safe(ROOT / 'installer.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(execute(args.apply, args.rollback), sort_keys=True))
    else:
        print(json.dumps(execute(), sort_keys=True))
