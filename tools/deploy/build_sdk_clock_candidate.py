"""Build the reviewed clock correction from pinned Git and installed hashes; never deploy."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

REPO = Path(__file__).resolve().parents[2]
SOURCE = '5f1854b801cdf9c020a21c199c8abbff98cef256'
OLD_SHA = 'e3f0176566d900ed4ee3c576778df465e02de7abbc2284c245b804e93f526877'
FILES = {
    'cloud': {'apps/web/public/js/admin-control.js': 'apps/web/public/js/admin-control.js',
              'apps/web/public/js/i18n-cloud-catalog.js': 'apps/web/public/js/i18n-cloud-catalog.js'},
    'edge': {'thirdhand_edge/lease.py': 'services/edge-agent/src/thirdhand_edge/lease.py'},
    'robot': {p: p for p in ('services/robot/src/control-policy.js', 'services/robot/src/remote_lease_guard.py')},
}
NAMES = {'edge': 'agent-sdk-timing-80ec1265764b8569', 'robot': 'robot-sdk-2fe4b77d3974d3c3'}
UNITS = {'edge': 'thirdhand-stage-edge-read-only.service', 'robot': 'thirdhand-tcp-calibration-robot.service'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pretty(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def git_bytes(revision, path):
    return subprocess.check_output(['git', 'show', revision + ':' + path], cwd=REPO)


def build(cloud_baseline, device_baseline, destination):
    raw = cloud_baseline.read_bytes()
    if sha(raw) != OLD_SHA:
        raise ValueError('Cloud baseline changed')
    cloud = json.loads(raw)
    device = json.loads(device_baseline.read_text(encoding='utf-8-sig'))
    if len(cloud['files']) != 4658 or device['context']['sdkConnected'] is not False or device['context']['readOnly'] is not True:
        raise ValueError('Unexpected inventory or SDK state')
    package = {'schema': 1, 'purpose': 'sdk-clock-fix', 'sourceCommit': SOURCE}
    for group, paths in FILES.items():
        before = cloud['files'] if group == 'cloud' else device[group]['files']
        if not all(p in before for p in paths):
            raise ValueError('Missing target')
        contents = {p: git_bytes(SOURCE, repo) for p, repo in paths.items()}
        after = {**before, **{p: sha(data) for p, data in contents.items()}}
        if {p for p in after if before.get(p) != after[p]} != set(paths):
            raise ValueError('Unexpected delta')
        item = {'before': before, 'after': after, 'changes': {p: base64.b64encode(data).decode() for p, data in contents.items()}}
        if group == 'cloud':
            manifest = pretty({**cloud, 'files': after})
            item.update(oldRelease='/opt/thirdhand-stage/releases/' + OLD_SHA[:16],
                        oldManifestSha256=OLD_SHA, newRelease='/opt/thirdhand-stage/releases/' + sha(manifest)[:16],
                        newManifestSha256=sha(manifest), manifestBase64=base64.b64encode(manifest).decode())
        else:
            baseline = device[group]
            old = PurePosixPath(baseline['source'])
            expected_tail = PurePosixPath('.local/share/thirdhand-stage-device/20261031/' + NAMES[group])
            if (not old.is_absolute() or '..' in old.parts or old.as_posix() != baseline['source']
                    or len(old.parts) != 3 + len(expected_tail.parts) or old.parts[1] != 'home'
                    or old.parts[3:] != expected_tail.parts or baseline['links']
                    or baseline['state']['ActiveState'] != 'active' or baseline['state']['NeedDaemonReload'] != 'no'):
                raise ValueError('Active device source changed')
            if any(before[p] != sha(git_bytes(SOURCE + '^', repo)) for p, repo in paths.items()):
                raise ValueError('Installed target differs from tested baseline')
            new = old.parent / (('agent' if group == 'edge' else 'robot') + '-sdk-clock-' + sha(pretty(after))[:16])
            home = PurePosixPath(*old.parts[:3])
            drop = home / '.config/systemd/user' / (UNITS[group] + '.d') / 'zzzzz-sdk-clock.conf'
            if group == 'edge':
                if set(baseline['pythonpath']) != {'PYTHONPATH=' + str(old), 'THIRDHAND_SDK_TIMING=0'}:
                    raise ValueError('Unexpected edge environment')
                config = '[Service]\nEnvironment=PYTHONPATH=' + str(new) + '\nEnvironment=THIRDHAND_SDK_TIMING=0\n'
            else:
                binary = home / 'ThirdHand/UIEAclub_ThirdHand_VLA/local/runtimes/node/bin/node'
                invocation = str(binary) + ' ' + str(old / 'services/robot/src/server.js')
                if 'argv[]=' + invocation + ' ;' not in baseline['state']['ExecStart']:
                    raise ValueError('Robot invocation changed')
                config = '[Service]\nExecStart=\nExecStart=' + str(binary) + ' ' + str(new / 'services/robot/src/server.js') + '\n'
            if str(drop) in baseline['unitHashes'] or any(not re.fullmatch('[a-f0-9]{64}', h) for h in baseline['unitHashes'].values()):
                raise ValueError('Unexpected unit baseline')
            item.update(oldSource=str(old), newSource=str(new), unit=UNITS[group], unitHashes=baseline['unitHashes'],
                        dropIn=str(drop), dropInText=config, dropInSha256=sha(config.encode()))
        package[group] = item
    packed = gzip.compress(pretty(package), mtime=0)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'sdk-clock-candidate.json.gz').write_bytes(packed)
    (destination / 'cloud-manifest.json').write_bytes(manifest)
    report = {'sourceCommit': SOURCE, 'packageSha256': sha(packed), 'packageBytes': len(packed),
              'cloudNew': package['cloud']['newRelease'], 'cloudManifestSha256': package['cloud']['newManifestSha256'],
              'changes': {g: {p: package[g]['after'][p] for p in FILES[g]} for g in FILES},
              'device': {g: {k: package[g][k] for k in ('oldSource', 'newSource', 'dropIn', 'dropInText', 'dropInSha256')} for g in NAMES}}
    (destination / 'summary.json').write_bytes(pretty(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-baseline', type=Path, required=True)
    parser.add_argument('--device-baseline', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.cloud_baseline, args.device_baseline, args.destination), indent=2))
