"""Build a fixed diagnostic-only package from Git plus public installed hashes."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

REPO = Path(__file__).resolve().parents[2]
SOURCE = '2bc817ce9249eece16b66da13339c5746458fab3'
OLD_SHA = '805921eeb03285b8b68a878c27870f69e116d68db7b26e05c9547c9fa1d3551d'
CLOUD = ('services/cloud-api/src/control/leases.js', 'services/device-relay/src/server.js', 'services/device-relay/src/lease-timing.js')
EDGE = ('bound_transport.py', 'lease_timing.py')
EDGE_RELATIVE = '.local/share/thirdhand-stage-device/20261031/agent-sdk-ab786c269838e18c'
EDGE_BOUND_BEFORE = 'c2ebfd381f032a06be3d7cc18e6d027d07f9f8c006be43dd6556f17f54265f8c'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pretty(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def build(cloud_baseline, device_baseline, destination):
    before_raw = cloud_baseline.read_bytes()
    if sha(before_raw) != OLD_SHA:
        raise ValueError('Cloud baseline changed')
    before = json.loads(before_raw)
    device = json.loads(device_baseline.read_text(encoding='utf-8-sig'))
    old_source = device['source']
    source = PurePosixPath(old_source)
    if (not source.is_absolute() or source.as_posix() != old_source or '..' in source.parts
            or len(source.parts) != 3 + len(PurePosixPath(EDGE_RELATIVE).parts)
            or source.parts[1] != 'home' or source.parts[3:] != PurePosixPath(EDGE_RELATIVE).parts
            or device['files'].get('thirdhand_edge/bound_transport.py') != EDGE_BOUND_BEFORE):
        raise ValueError('Active device source changed')
    if device.get('pythonpath') != ['PYTHONPATH=' + old_source] or device.get('timingEnabled') is not False:
        raise ValueError('Active device configuration changed')
    if len(before['files']) != 4657 or CLOUD[-1] in before['files'] or 'thirdhand_edge/lease_timing.py' in device['files']:
        raise ValueError('Unexpected inventory')
    cloud_bytes = {p: subprocess.check_output(['git', 'show', SOURCE + ':' + p], cwd=REPO) for p in CLOUD}
    edge_bytes = {'thirdhand_edge/' + p: subprocess.check_output(['git', 'show', SOURCE + ':services/edge-agent/src/thirdhand_edge/' + p], cwd=REPO) for p in EDGE}
    after = json.loads(before_raw)
    after['files'].update({p: sha(raw) for p, raw in cloud_bytes.items()})
    manifest = pretty(after)
    edge_after = {**device['files'], **{p: sha(raw) for p, raw in edge_bytes.items()}}
    edge_hash = sha(pretty(edge_after))
    package = dict(schema=1, purpose='sdk-segment-timing', sourceCommit=SOURCE,
                   cloud=dict(oldRelease='/opt/thirdhand-stage/releases/' + OLD_SHA[:16],
                              oldManifestSha256=OLD_SHA, before=before['files'], after=after['files'],
                              newRelease='/opt/thirdhand-stage/releases/' + sha(manifest)[:16],
                              newManifestSha256=sha(manifest), manifestBase64=base64.b64encode(manifest).decode(),
                              changes={p: base64.b64encode(raw).decode() for p, raw in cloud_bytes.items()}),
                   edge=dict(oldSource=old_source, newSource=old_source.rsplit('/', 1)[0] + '/agent-sdk-timing-' + edge_hash[:16],
                             before=device['files'], after=edge_after, unitHashes=device['unitHashes'],
                             changes={p: base64.b64encode(raw).decode() for p, raw in edge_bytes.items()}))
    packed = gzip.compress(pretty(package), mtime=0)
    report = dict(sourceCommit=SOURCE, packageSha256=sha(packed), packageBytes=len(packed),
                  cloudOld=package['cloud']['oldRelease'], cloudNew=package['cloud']['newRelease'],
                  cloudManifestSha256=sha(manifest), cloudChanged={p: after['files'][p] for p in CLOUD},
                  cloudFileCount=len(after['files']), edgeOld=old_source, edgeNew=package['edge']['newSource'],
                  edgeChanged={p: edge_after[p] for p in edge_bytes}, edgeFileCount=len(edge_after),
                  environment='THIRDHAND_SDK_TIMING=1', databaseMigrations=[], permissions=[], newPorts=[], sdkActions=0)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'sdk-timing-candidate.json.gz').write_bytes(packed)
    (destination / 'candidate-summary.json').write_bytes(pretty(report))
    (destination / 'cloud-manifest.json').write_bytes(manifest)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-baseline', type=Path, required=True)
    parser.add_argument('--device-baseline', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.cloud_baseline, args.device_baseline, args.destination), indent=2))
