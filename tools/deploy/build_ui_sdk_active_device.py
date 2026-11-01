"""Reproduce C8's corrected five-file delta against the actual C3c/C3e snapshot.

The installer clones complete pinned sources into new directories; this builder
does not make in-place changes or include any credentials/configuration content.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PINS = REPO / 'deploy/public-access/staging/device/c8-active-pins.json'
PINS_SHA = '103171b62779c34408845549dc68fe8be7aee0b7b8b83e8be5bf18ae729a34fa'


def build(baseline, destination):
    raw = PINS.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PINS_SHA:
        raise ValueError('Active pins changed')
    pins = json.loads(raw)
    spec = importlib.util.spec_from_file_location('c8_delta_builder', REPO / 'tools/deploy/build_ui_sdk_device.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    agent, robot = pins['snapshots']
    module.AGENT = agent['old'] + '/thirdhand_edge/'
    module.ROBOT = robot['old'] + '/services/robot/src/'
    for name in module.BEFORE:
        group, prefix = (robot, 'services/robot/src/') if name in ('remote-gateway.js', 'robot-controller.js', 'startouch_bridge.py') else (agent, 'thirdhand_edge/')
        module.BEFORE[name] = group['before'][prefix+name]
    report = module.build(baseline, destination)
    # Python 3.11 delegates mtime=0 gzip headers to zlib (OS varies by host).
    # Pin the informational OS byte; payload/CRC are unchanged.
    packed = bytearray((destination / 'device.delta.json.gz').read_bytes())
    packed[9] = 255
    (destination / 'device.delta.json.gz').write_bytes(packed)
    report['packageSha256'] = hashlib.sha256(packed).hexdigest()
    if report['packageSha256'] != pins['packageSha256'] or report['afterHashes'] != pins['changes']:
        raise ValueError('Corrected candidate mismatch')
    (destination / 'active-pins.json').write_bytes(raw)
    (destination / 'candidate-summary.json').write_text(json.dumps(report, sort_keys=True, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.baseline, args.destination), sort_keys=True))
