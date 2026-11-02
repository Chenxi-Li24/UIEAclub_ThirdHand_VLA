"""Build the pinned browser heartbeat patch; never upload or apply it."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

REPO = Path(__file__).resolve().parents[2]
SOURCE = '40d2dacb7067c294885c706161188bf63181e102'
OLD_SHA = 'd5284b8679ff90e88f0c2138e8b31c9eb53f6197ddef09eb2982300943fc97b7'
FILES = {'cloud': ('apps/web/public/js/admin-control.js',
                   'services/cloud-api/src/control/control-channel.js',
                   'services/cloud-api/src/control/websocket.js',
                   'services/cloud-api/src/control/leases.js',
                   'services/cloud-api/src/server.js'),
         'robot': ('services/robot/src/startouch-bridge.js',)}
BASE = PurePosixPath('/home/nieqingcao/.local/share/thirdhand-stage-device/20261031')
UNITS = {'edge': 'thirdhand-stage-edge-read-only.service',
         'robot': 'thirdhand-tcp-calibration-robot.service'}
NAMES = {'edge': 'agent-sdk-clock-a963153d56dac68d', 'robot': 'robot-sdk-clock-26c8339436ca6daa'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


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
    if (len(cloud['files']) != 4658 or device['context']['sdkConnected'] is not False
            or device['context']['readOnly'] is not True):
        raise ValueError('Unexpected inventory or SDK state')
    for group, count in [('edge', 24), ('robot', 37)]:
        value = device[group]
        if (value['source'] != str(BASE / NAMES[group]) or value['links'] or len(value['files']) != count
                or value['state']['ActiveState'] != 'active' or value['state']['NeedDaemonReload'] != 'no'):
            raise ValueError('Active device source changed')
        for path, digest in value['files'].items():
            if PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts or len(digest) != 64:
                raise ValueError('Invalid device inventory')
    if set(device['edge']['pythonpath']) != {'PYTHONPATH=' + str(BASE / NAMES['edge']), 'THIRDHAND_SDK_TIMING=0'}:
        raise ValueError('Edge configuration changed')
    package = {'schema': 1, 'purpose': 'sdk-browser-heartbeat-fix', 'sourceCommit': SOURCE,
               'edgeBaseline': device['edge']}
    for group, paths in FILES.items():
        before = cloud['files'] if group == 'cloud' else device[group]['files']
        if any(before.get(p) != sha(git_bytes(SOURCE + '^', p)) for p in paths):
            raise ValueError('Installed target differs from tested baseline')
        contents = {p: git_bytes(SOURCE, p) for p in paths}
        after = {**before, **{p: sha(data) for p, data in contents.items()}}
        if {p for p in after if before.get(p) != after[p]} != set(paths):
            raise ValueError('Unexpected delta')
        item = {'before': before, 'after': after,
                'changes': {p: base64.b64encode(data).decode() for p, data in contents.items()}}
        if group == 'cloud':
            manifest = pretty({**cloud, 'files': after})
            item.update(oldRelease='/opt/thirdhand-stage/releases/' + OLD_SHA[:16], oldManifestSha256=OLD_SHA,
                        newRelease='/opt/thirdhand-stage/releases/' + sha(manifest)[:16],
                        newManifestSha256=sha(manifest), manifestBase64=base64.b64encode(manifest).decode())
        else:
            old = BASE / NAMES[group]
            binary = '/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/local/runtimes/node/bin/node'
            if 'argv[]=' + binary + ' ' + str(old / 'services/robot/src/server.js') + ' ;' not in device[group]['state']['ExecStart']:
                raise ValueError('Robot invocation changed')
            new = BASE / ('robot-sdk-browser-heartbeat-' + sha(pretty(after))[:16])
            drop = PurePosixPath('/home/nieqingcao/.config/systemd/user') / (UNITS[group] + '.d') / 'zzzzzz-sdk-browser-heartbeat.conf'
            config = '[Service]\nExecStart=\nExecStart=' + binary + ' ' + str(new / 'services/robot/src/server.js') + '\n'
            if str(drop) in device[group]['unitHashes']:
                raise ValueError('Drop-in already exists')
            item.update(oldSource=str(old), newSource=str(new), unit=UNITS[group],
                        unitHashes=device[group]['unitHashes'], dropIn=str(drop), dropInText=config,
                        dropInSha256=sha(config.encode()))
        package[group] = item
    packed = gzip.compress(pretty(package), mtime=0)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'sdk-browser-heartbeat-candidate.json.gz').write_bytes(packed)
    (destination / 'cloud-manifest.json').write_bytes(manifest)
    report = {'sourceCommit': SOURCE, 'packageSha256': sha(packed), 'packageBytes': len(packed),
              'cloudNew': package['cloud']['newRelease'], 'cloudManifestSha256': package['cloud']['newManifestSha256'],
              'changes': {g: {p: package[g]['after'][p] for p in FILES[g]} for g in FILES},
              'robot': {k: package['robot'][k] for k in ('oldSource', 'newSource', 'dropIn', 'dropInText', 'dropInSha256')}}
    (destination / 'summary.json').write_bytes(pretty(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-baseline', type=Path, required=True)
    parser.add_argument('--device-baseline', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.cloud_baseline, args.device_baseline, args.destination), indent=2))
