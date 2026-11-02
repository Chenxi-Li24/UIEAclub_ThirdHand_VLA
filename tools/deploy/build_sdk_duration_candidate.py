"""Build an offline fixed SDK lease-duration candidate, preserving installed IK code."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

REPO = Path(__file__).resolve().parents[2]
SOURCE = '7d16ccaec6387c0b7b3956b8018afda1a875f4b0'
OLD_SHA = 'a3ca345673912070924dc28d5141c1b0c7e5f736efcaaee7edc6aaf5085a38ad'
FILES = {
    'cloud': ('platform/storage/src/leases.js', 'services/cloud-api/src/control/leases.js'),
    'edge': ('services/edge-agent/src/thirdhand_edge/lease.py',),
    'robot': ('services/robot/src/control-policy.js', 'services/robot/src/lease-watchdog.js',
              'services/robot/src/startouch-bridge.js', 'services/robot/src/remote_lease_guard.py',
              'services/robot/src/startouch_bridge.py'),
}
NAMES = {'edge': 'agent-sdk-clock-a963153d56dac68d', 'robot': 'robot-sdk-browser-heartbeat-f72bba77f012ba0c'}
UNITS = {'edge': 'thirdhand-stage-edge-read-only.service', 'robot': 'thirdhand-tcp-calibration-robot.service'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pretty(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def git_bytes(revision, path):
    return subprocess.check_output(['git', 'show', revision + ':' + path], cwd=REPO)


def merge_worker(before, after, installed):
    """Replace only two exact functions; refuse drift inside either changed function."""
    old, new, actual = (value.decode('utf-8') for value in (before, after, installed))
    for name in ('_require_remote_lease', 'connect'):
        marker = '    def ' + name + '('
        start, changed = old.index(marker), new.index(marker)
        previous = old[start:old.index('\n    def ', start + len(marker))]
        replacement = new[changed:new.index('\n    def ', changed + len(marker))]
        if actual.count(previous) != 1:
            raise ValueError('Installed worker function drift: ' + name)
        actual = actual.replace(previous, replacement, 1)
        old = old.replace(previous, replacement, 1)
    if old != new:
        raise ValueError('Worker changes outside approved functions')
    return actual.encode()


def build(cloud_baseline, device_baseline, installed_worker, destination):
    raw = cloud_baseline.read_bytes()
    if sha(raw) != OLD_SHA:
        raise ValueError('Cloud baseline changed')
    cloud = json.loads(raw)
    device = json.loads(device_baseline.read_text(encoding='utf-8-sig'))
    if len(cloud['files']) != 4658 or device['context']['sdkConnected'] is not False or device['context']['readOnly'] is not True:
        raise ValueError('Unexpected inventory or SDK state')
    package = {'schema': 1, 'purpose': 'sdk-duration-fix', 'sourceCommit': SOURCE}
    for group, paths in FILES.items():
        before = cloud['files'] if group == 'cloud' else device[group]['files']
        contents = {}
        for path in paths:
            target = path.removeprefix('services/edge-agent/src/') if group == 'edge' else path
            previous, updated = git_bytes(SOURCE + '^', path), git_bytes(SOURCE, path)
            if group == 'robot' and path.endswith('/startouch_bridge.py'):
                actual = installed_worker.read_bytes()
                if sha(actual) != before.get(target):
                    raise ValueError('Installed worker digest changed')
                updated = merge_worker(previous, updated, actual)
            elif sha(previous) != before.get(target):
                raise ValueError('Installed target differs from tested baseline: ' + target)
            contents[target] = updated
        after = {**before, **{path: sha(data) for path, data in contents.items()}}
        if {path for path in after if before.get(path) != after[path]} != set(contents):
            raise ValueError('Unexpected delta')
        for path in after:
            p = PurePosixPath(path)
            if p.is_absolute() or '..' in p.parts or p.as_posix() != path:
                raise ValueError('Unsafe inventory path')
        item = {'before': before, 'after': after,
                'changes': {path: base64.b64encode(data).decode() for path, data in contents.items()}}
        if group == 'cloud':
            manifest = pretty({**cloud, 'files': after})
            item.update(oldRelease='/opt/thirdhand-stage/releases/' + OLD_SHA[:16], oldManifestSha256=OLD_SHA,
                        newRelease='/opt/thirdhand-stage/releases/' + sha(manifest)[:16],
                        newManifestSha256=sha(manifest), manifestBase64=base64.b64encode(manifest).decode())
        else:
            baseline = device[group]
            old = PurePosixPath(baseline['source'])
            if (not old.is_absolute() or '..' in old.parts or old.parts[1] != 'home' or old.name != NAMES[group]
                    or old.parts[3:-1] != ('.local', 'share', 'thirdhand-stage-device', '20261031')
                    or len(before) != (24 if group == 'edge' else 37) or baseline['links']
                    or baseline['state']['ActiveState'] != 'active' or baseline['state']['NeedDaemonReload'] != 'no'):
                raise ValueError('Device baseline drift')
            home = PurePosixPath(*old.parts[:3])
            new = old.parent / (('agent' if group == 'edge' else 'robot') + '-sdk-duration-' + sha(pretty(after))[:16])
            drop = home / '.config/systemd/user' / (UNITS[group] + '.d') / 'zzzzzzz-sdk-duration.conf'
            if str(drop) in baseline['unitHashes']:
                raise ValueError('Drop-in already exists')
            if group == 'edge':
                if set(baseline['pythonpath']) != {'PYTHONPATH=' + str(old), 'THIRDHAND_SDK_TIMING=0'}:
                    raise ValueError('Edge environment changed')
                config = '[Service]\nEnvironment=PYTHONPATH=' + str(new) + '\n'
            else:
                binary = home / 'ThirdHand/UIEAclub_ThirdHand_VLA/local/runtimes/node/bin/node'
                if 'argv[]=' + str(binary) + ' ' + str(old / 'services/robot/src/server.js') + ' ;' not in baseline['state']['ExecStart']:
                    raise ValueError('Robot invocation changed')
                config = '[Service]\nExecStart=\nExecStart=' + str(binary) + ' ' + str(new / 'services/robot/src/server.js') + '\n'
            item.update(oldSource=str(old), newSource=str(new), unit=UNITS[group], unitHashes=baseline['unitHashes'],
                        oldState=baseline['state'], dropIn=str(drop), dropInText=config, dropInSha256=sha(config.encode()))
        package[group] = item
    if PurePosixPath(package['edge']['oldSource']).parent != PurePosixPath(package['robot']['oldSource']).parent:
        raise ValueError('Device roots differ')
    packed = gzip.compress(pretty(package), mtime=0)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'sdk-duration-candidate.json.gz').write_bytes(packed)
    (destination / 'cloud-manifest.json').write_bytes(manifest)
    report = {'sourceCommit': SOURCE, 'packageSha256': sha(packed), 'packageBytes': len(packed),
              'cloudNew': package['cloud']['newRelease'], 'cloudManifestSha256': package['cloud']['newManifestSha256'],
              'changes': {g: {p: package[g]['after'][p] for p in package[g]['changes']} for g in FILES},
              'device': {g: {k: package[g][k] for k in ('oldSource', 'newSource', 'dropIn', 'dropInText', 'dropInSha256')} for g in ('edge', 'robot')}}
    (destination / 'summary.json').write_bytes(pretty(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cloud-baseline', 'device-baseline', 'installed-worker', 'destination'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.cloud_baseline, args.device_baseline, args.installed_worker, args.destination), indent=2))
