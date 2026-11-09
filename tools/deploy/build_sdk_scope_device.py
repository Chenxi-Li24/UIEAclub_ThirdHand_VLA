"""Build the eight-file SDK-scope + latest-state delta from pinned sources.

The baseline is read-only. Existing C8 patches retain the site's archive uploader
and stop/worker code; only three additional scope protocol files are replaced.
"""
import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]
SOURCE = '3512410788da5e4e2878137e4ddd7e172e5bcdd4'
OLD_PINS = REPO / 'deploy/public-access/staging/device/c8-active-pins.json'
OLD_PINS_SHA = '103171b62779c34408845549dc68fe8be7aee0b7b8b83e8be5bf18ae729a34fa'
EXTRA = {'lease.py': (0, 'thirdhand_edge/lease.py', 'services/edge-agent/src/thirdhand_edge/lease.py'),
         'bound_transport.py': (0, 'thirdhand_edge/bound_transport.py', 'services/edge-agent/src/thirdhand_edge/bound_transport.py'),
         'control-policy.js': (1, 'services/robot/src/control-policy.js', 'services/robot/src/control-policy.js')}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def source_bytes(name):
    return subprocess.run(['git', 'show', SOURCE + ':' + name], cwd=REPO,
                          capture_output=True, check=True).stdout


def build(baseline, destination):
    raw = OLD_PINS.read_bytes()
    if sha(raw) != OLD_PINS_SHA:
        raise ValueError('Previous source pins changed')
    pins = json.loads(raw)
    spec = importlib.util.spec_from_file_location('c8_active_builder', REPO / 'tools/deploy/build_ui_sdk_active_device.py')
    previous = importlib.util.module_from_spec(spec); spec.loader.exec_module(previous)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='thirdhand-sdk-scope-', dir=destination.parent) as tmp:
        if Path(tmp).resolve().parent != destination.parent:
            raise ValueError('Temporary build path escaped destination parent')
        old_candidate = Path(tmp) / 'state'
        previous.build(baseline, old_candidate)
        package = json.loads(gzip.decompress((old_candidate / 'device.delta.json.gz').read_bytes()))
    changes = {name: base64.b64decode(data, validate=True) for name, data in package['changes'].items()}
    for name, (index, relative, source) in EXTRA.items():
        group = pins['snapshots'][index]
        if sha((baseline / name).read_bytes()) != group['before'][relative]:
            raise ValueError('Active SDK protocol baseline changed: ' + name)
        value = source_bytes(source)
        changes[group['old'] + '/' + relative] = value
        group['after'][relative] = sha(value)
    if len(changes) != 8:
        raise ValueError('Unexpected deployment scope')
    for index, group in enumerate(pins['snapshots']):
        group['new'] = ('agent-sdk-' if index == 0 else 'robot-sdk-') + sha(json.dumps(group['after'], sort_keys=True).encode())[:16]
    agent, robot = pins['snapshots']
    prefix = '@HOME@/.local/share/thirdhand-stage-device/20261031/'
    pins['dropins'] = {
        'thirdhand-stage-edge-read-only.service.d/zzz-sdk-scope-state.conf': '[Service]\nEnvironment="PYTHONPATH=' + prefix + agent['new'] + '"\n',
        'thirdhand-tcp-calibration-robot.service.d/zzz-sdk-scope-state.conf': '[Service]\nExecStart=\nExecStart=@HOME@/ThirdHand/UIEAclub_ThirdHand_VLA/local/runtimes/node/bin/node ' + prefix + robot['new'] + '/services/robot/src/server.js\n',
    }
    pins['changes'] = {name: sha(value) for name, value in changes.items()}
    package = {'format': 1, 'sourceCommit': SOURCE, 'changes': {name: base64.b64encode(value).decode() for name, value in changes.items()}}
    packed = bytearray(gzip.compress(json.dumps(package, sort_keys=True, separators=(',', ':')).encode(), mtime=0))
    packed[9] = 255
    pins['packageSha256'] = sha(packed)
    pins_raw = (json.dumps(pins, sort_keys=True, indent=2) + '\n').encode()
    report = {'sourceCommit': SOURCE, 'packageSha256': sha(packed), 'pinsSha256': sha(pins_raw),
              'sourceChanges': 8, 'addedFiles': 2, 'changedFiles': 6, 'preservedFiles': 52,
              'newSnapshots': [group['new'] for group in pins['snapshots']], 'automaticSdkConnect': False,
              'motionCommands': 0, 'archiveUploaderChanged': False, 'credentialsChanged': False}
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'device.delta.json.gz').write_bytes(packed)
    (destination / 'active-pins.json').write_bytes(pins_raw)
    (destination / 'candidate-summary.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.baseline, args.destination), sort_keys=True))
