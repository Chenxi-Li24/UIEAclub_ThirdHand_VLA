"""C8b: patch the pinned live read-only snapshot, preserving its control policy.

The site's archive uploader predates Git. Keep it byte-identical; give the new
latest-only worker a private copy of the tested upload transport instead.
"""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[2]
SOURCE = '7e65b5d3b59fb7359dec1262d1f7a31c9a63139d'
BEFORE = {
    'runtime.py': '00d92659932fd0c1b4ede4732384a43815c2f900e978fad58c32d7a6f4b5a340',
    'telemetry.py': 'ba16dab3ab6371c860bac284386be0fff7bc7969e454ec34f96befcd6ebc3832',
    'upload.py': '2e8fa8645c6f966e6570fbcad681b2f206eca204e8ee584b5ebf1e677a3d8652',
    'remote-gateway.js': '15a5eeb794cba2c1efdfdf7489ae234b7dbce47efac61765b544dae86d56baf8',
    'robot-controller.js': '2cbeafe497b30b7a8effecde3e59dae6c472d30dd77b7785c3988eac43b696da',
    'startouch_bridge.py': '126a8055544c04207d190dff0da31c0ba3407799ffcaa9d7803b3bcab08b2d3d',
}
AGENT = 'agent-source/thirdhand_edge/'
ROBOT = 'robot/services/robot/src/'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def once(raw, old, new):
    if raw.count(old) != 1:
        raise ValueError('Site patch anchor changed')
    return raw.replace(old, new, 1)


def read_source(name):
    return subprocess.run(['git', 'show', SOURCE + ':services/edge-agent/src/thirdhand_edge/' + name],
                          cwd=REPO, capture_output=True, check=True).stdout


def build(baseline, destination, source=read_source):
    originals = {name: (baseline / name).read_bytes() for name in BEFORE}
    if any(sha(raw) != BEFORE[name] for name, raw in originals.items()):
        raise ValueError('Ubuntu baseline changed')
    runtime = originals['runtime.py']
    branch = b'''    if role == "state":
        from .latest_state import LatestStateClient, publish_latest
        robot = RobotClient(base_url=config["robot_origin"], token_file=config["robot_token_file"])
        publish_latest(robot, LatestStateClient(device), context_path=directory / "connection.json",
                       device_id=device.device_id, boot_id=boot, versions=config.get("versions"))
        return
'''
    runtime = once(runtime, b'    box = Outbox(directory / "outbox.sqlite", device_id=device.device_id,',
                   branch + b'    box = Outbox(directory / "outbox.sqlite", device_id=device.device_id,')
    runtime = once(runtime, b'("capture", "upload", "control", *((', b'("capture", "upload", "control", "state", *((')
    runtime = once(runtime, b'choices=("control", "capture", "upload", "media")',
                   b'choices=("control", "capture", "upload", "media", "state")')
    gateway = once(originals['remote-gateway.js'], b'sequence:++sourceSequence,receivedAt:',
                   b'sequence:++sourceSequence,sourceMonotonicNs:Number(process.hrtime.bigint()),receivedAt:')
    latest = once(source('latest_state.py'), b'from .upload import TelemetryUploadClient',
                  b'from .state_upload import TelemetryUploadClient')
    contents = {AGENT + 'runtime.py': runtime, AGENT + 'telemetry.py': source('telemetry.py'),
                AGENT + 'latest_state.py': latest, AGENT + 'state_upload.py': source('upload.py'),
                ROBOT + 'remote-gateway.js': gateway}
    for name, raw in contents.items():
        if name.endswith('.py'):
            compile(raw, name, 'exec')
    before = {AGENT + n: BEFORE[n] for n in ('runtime.py', 'telemetry.py')}
    before.update({ROBOT + 'remote-gateway.js': BEFORE['remote-gateway.js'],
                   AGENT + 'latest_state.py': None, AGENT + 'state_upload.py': None})
    protected = {AGENT + 'upload.py': BEFORE['upload.py'], ROBOT + 'robot-controller.js': BEFORE['robot-controller.js'],
                 ROBOT + 'startouch_bridge.py': BEFORE['startouch_bridge.py']}
    package = {'format': 1, 'sourceCommit': SOURCE, 'beforeHashes': before, 'protectedHashes': protected,
               'afterHashes': {n: sha(v) for n, v in contents.items()},
               'changes': {n: base64.b64encode(v).decode() for n, v in contents.items()}}
    packed = gzip.compress(json.dumps(package, sort_keys=True, separators=(',', ':')).encode(), mtime=0)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'device.delta.json.gz').write_bytes(packed)
    report = {k: v for k, v in package.items() if k != 'changes'}
    report.update(packageSha256=sha(packed), packageBytes=len(packed), automaticSdkConnect=False,
                  motionCommands=0, archiveUploaderChanged=False, credentialsChanged=False)
    (destination / 'candidate-summary.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.baseline, args.destination), sort_keys=True))
