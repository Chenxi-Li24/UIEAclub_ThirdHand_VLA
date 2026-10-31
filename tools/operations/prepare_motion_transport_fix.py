"""Prepare the first, read-only transport candidate. Never deploy or contact hosts.

Default: validate pinned local baselines and print a review only. --build writes
an immutable candidate directory. An installer is deliberately not included:
actual service/unit/source inventories must be reviewed before one is prepared.
"""
import argparse
import ast
import base64
import copy
import difflib
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile


REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / '.superpowers/sdd/2026-10-30-public-access-rollout'
WORK = REPO / '.superpowers/sdd/2026-10-31-remote-motion-readiness'
PINS = {
    'C5-history-display.delta.json.gz': '9b23fbd039907452e3aac078605bb8263c1c9ce8f00b177e022b569373a101fb',
    'C3a-agent-source.tar.gz': '5d093cd7e4a6f65afbf056f026d1d50b8522d06af020cf04a7b3c6c3d1328895',
    'C3a-ubuntu-installed-final-public.json': '3491b192790b098f08980a210dac188efe50f6475ba573a2c711ca697573ebc3',
    'C2i-apply-coalesced.py': '94b1461a5651057f2cc34d9d631ce057e5dd061bbf61f3004809cf7db19c2373',
}
C5_MANIFEST = 'e6d791d66ca8ad1f59a85e076df5de360cea6ec9ce746643caaf9507baf55ba4'
C5_RELEASE = '/opt/thirdhand-stage/releases/6187bbbe8ec4d5e8'
AGENT_SOURCE = '/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/agent-source'
CAMERA_SOURCE = '/home/nieqingcao/.local/share/thirdhand-stage-camera/20261031/source-e9c8e33a97903125'
CAMERA_MANIFEST = 'e9c8e33a97903125809ea107571ab9a4abeb003abc293c36846c09dd3ce4edc4'
CLOUD_FILE = 'services/cloud-api/src/control/websocket.js'
AGENT_CHANGES = {'thirdhand_edge/' + name for name in ('media_upload.py', 'media_publisher.py', 'upload.py', 'runtime.py')}
CAMERA_CHANGES = {'thirdhand_edge/' + name for name in ('media_upload.py', 'media_publisher.py', 'camera_runtime.py')}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def pretty(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def checked_bytes(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('Regular non-symlink source required: ' + str(path))
    raw = path.read_bytes()
    if re.search(rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----\s*[A-Za-z0-9+/=\s]{32,}-----END', raw):
        raise ValueError('Private key material in source')
    return raw


def pinned(directory, name):
    raw = checked_bytes(directory / name)
    if sha(raw) != PINS[name]:
        raise ValueError('Baseline digest mismatch: ' + name)
    return raw


def module_name(name):
    parts = PurePosixPath(name).parts
    if len(parts) != 2 or parts[0] != 'thirdhand_edge' or not parts[1].endswith('.py'):
        raise ValueError('Unexpected source member: ' + name)
    return name


def agent_before(archive, receipt):
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        for entry in tar:
            if not entry.isfile() or entry.name in contents:
                raise ValueError('Non-regular or duplicate baseline member')
            if entry.name == 'agent-source-manifest.json':
                continue
            module_name(entry.name)
            contents[entry.name] = tar.extractfile(entry).read()
    hashes = {name.removeprefix('agent-source/'): value for name, value in receipt['files'].items()
              if name.startswith('agent-source/thirdhand_edge/') and name.endswith('.py')}
    if len(hashes) != 20 or set(contents) != set(hashes):
        raise ValueError('Installed agent receipt does not match twenty baseline modules')
    return contents, hashes


def camera_before(script):
    # Parse constants; never execute the historical installer.
    values = [node.args[0].value for node in ast.walk(ast.parse(script.decode()))
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name) and node.func.value.id == 'base64'
              and node.func.attr == 'b64decode' and node.args
              and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]
    if len(values) != 1:
        raise ValueError('Expected one immutable camera payload')
    value = json.loads(gzip.decompress(base64.b64decode(values[0], validate=True)))
    contents = {module_name(name): base64.b64decode(raw, validate=True) for name, raw in value['files'].items()}
    hashes = value['hashes']
    if len(contents) != 20 or set(contents) != set(hashes) or sha(canonical(hashes)) != CAMERA_MANIFEST:
        raise ValueError('Camera baseline manifest mismatch')
    if any(sha(raw) != hashes[name] for name, raw in contents.items()):
        raise ValueError('Camera baseline content mismatch')
    return contents, hashes


def source_archive(contents, manifest):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w') as tar:
            for name, data in sorted({**contents, 'source-manifest.json': pretty(manifest)}.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                tar.addfile(info, io.BytesIO(data))
    return output.getvalue()


def snapshot(repo, kind, before, expected, permitted, new_contents):
    after, unavailable_before, recovery = {}, [], []
    for name in sorted(expected):
        original = before[name]
        if name in permitted:
            after[name] = new_contents[name]
            if sha(original) != expected[name]:
                unavailable_before.append(name)
        elif sha(original) == expected[name]:
            after[name] = original
        elif kind == 'agent' and name == 'thirdhand_edge/capture.py':
            # C3a repaired this file after its initial tar was built. The final
            # installed public receipt is authoritative, not that stale tar.
            recovered = checked_bytes(repo / 'services/edge-agent/src' / name)
            if sha(recovered) != expected[name]:
                raise ValueError('Installed capture baseline bytes unavailable')
            after[name] = recovered
            recovery.append(name)
        else:
            raise ValueError('Unchanged installed baseline bytes unavailable: ' + name)
    hashes = {name: sha(raw) for name, raw in after.items()}
    changed = sorted(name for name in hashes if hashes[name] != expected[name])
    if set(changed) != permitted:
        raise ValueError('Candidate change set differs from the exact allowlist: ' + kind)
    digest = sha(canonical(hashes))
    manifest = {'format': 1, 'role': kind + '-transport-candidate', 'automaticSdkConnect': False,
                'files': hashes, 'baselineFiles': expected, 'changedFiles': changed,
                'baselineAuthority': 'installed-final-public-receipt' if kind == 'agent' else 'C2i-immutable-payload',
                'installedBaselineRecovery': recovery, 'unavailableBeforeContents': unavailable_before}
    target = (Path(AGENT_SOURCE).parent / ('agent-source-' + digest[:16]) if kind == 'agent'
              else Path(CAMERA_SOURCE).parent / ('source-' + digest[:16]))
    result = {'sourceDigest': digest, 'manifestSha256': sha(pretty(manifest)), 'newSource': target.as_posix(),
              'baselineAuthority': manifest['baselineAuthority'], 'changedFiles': changed,
              'files': hashes, 'installedBaselineRecovery': recovery,
              'unavailableBeforeContents': unavailable_before}
    return source_archive(after, manifest), result


def validate_remote_inventory(value, agent_hashes, camera_hashes):
    try:
        valid = value['sources'] == {'agent': agent_hashes, 'camera': camera_hashes}
        valid = valid and value['cameraManifestSha256'] == CAMERA_MANIFEST
        valid = valid and value['context']['sdkConnected'] is False and value['context']['readOnly'] is True
        for role, source, fragment in [
            ('edge', AGENT_SOURCE, '/home/nieqingcao/.config/systemd/user/thirdhand-stage-edge-read-only.service'),
            ('camera', CAMERA_SOURCE, '/etc/systemd/system/thirdhand-stage-camera-publisher.service'),
        ]:
            unit = value['units'][role]
            valid = valid and unit['pythonPath'] == source and unit['FragmentPath'] == fragment
            valid = valid and unit['DropInPaths'] == '' and unit['ActiveState'] == 'active'
        valid = valid and isinstance(value['checkedAt'], str)
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise ValueError('Remote inventory mismatch: source, unit or SDK baseline')


def validate_cloud_inventory(value, websocket_hash):
    if (value.get('verified') is not True or value.get('oldRelease') != C5_RELEASE
            or value.get('manifestSha256') != C5_MANIFEST
            or value.get('websocketSha256') != websocket_hash
            or value.get('activeLeases') != 0 or isinstance(value.get('activeLeases'), bool)):
        raise ValueError('Cloud inventory mismatch: release, source or active leases')


def prepare_candidate(repo, baseline):
    repo, baseline = Path(repo), Path(baseline)
    c5 = json.loads(gzip.decompress(pinned(baseline, 'C5-history-display.delta.json.gz')))
    previous_manifest = base64.b64decode(c5['manifestBase64'], validate=True)
    if sha(previous_manifest) != C5_MANIFEST or c5['archiveSha256'][:16] != Path(C5_RELEASE).name:
        raise ValueError('C5 release identity mismatch')
    previous = json.loads(previous_manifest)
    cloud_remote_raw = checked_bytes(repo / '.superpowers/sdd/2026-10-31-remote-motion-readiness/transport-cloud-before.json')
    cloud_remote = json.loads(cloud_remote_raw)
    validate_cloud_inventory(cloud_remote, previous['files'][CLOUD_FILE])
    new_manifest = copy.deepcopy(previous)
    cloud_source = checked_bytes(repo / CLOUD_FILE)
    new_manifest['files'][CLOUD_FILE] = sha(cloud_source)
    if {name for name in new_manifest['files'] if new_manifest['files'][name] != previous['files'][name]} != {CLOUD_FILE}:
        raise ValueError('Cloud candidate must change only the control websocket module')
    manifest = pretty(new_manifest)
    cloud = {'format': 1, 'oldRelease': C5_RELEASE, 'oldManifestSha256': C5_MANIFEST,
             'newRelease': '/opt/thirdhand-stage/releases/' + sha(manifest)[:16],
             'releaseIdBasis': 'new-manifest-sha256-prefix', 'manifestSha256': sha(manifest),
             'manifestBase64': base64.b64encode(manifest).decode(),
             'beforeHashes': {CLOUD_FILE: previous['files'][CLOUD_FILE]},
             'changes': {CLOUD_FILE: base64.b64encode(cloud_source).decode()}}
    agent, agent_hashes = agent_before(pinned(baseline, 'C3a-agent-source.tar.gz'),
        json.loads(pinned(baseline, 'C3a-ubuntu-installed-final-public.json')))
    camera, camera_hashes = camera_before(pinned(baseline, 'C2i-apply-coalesced.py'))
    remote_raw = checked_bytes(repo / '.superpowers/sdd/2026-10-31-remote-motion-readiness/transport-remote-before.json')
    remote = json.loads(remote_raw)
    validate_remote_inventory(remote, agent_hashes, camera_hashes)
    new_contents = {name: checked_bytes(repo / 'services/edge-agent/src' / name)
                    for name in sorted(AGENT_CHANGES | CAMERA_CHANGES)}
    agent_archive, agent_summary = snapshot(repo, 'agent', agent, agent_hashes, AGENT_CHANGES, new_contents)
    camera_archive, camera_summary = snapshot(repo, 'camera', camera, camera_hashes, CAMERA_CHANGES, new_contents)
    baseline_public = {
        'cloud': {'oldRelease': C5_RELEASE, 'manifestSha256': C5_MANIFEST, 'files': cloud['beforeHashes']},
        'agent': {'source': AGENT_SOURCE, 'receiptSha256': PINS['C3a-ubuntu-installed-final-public.json'], 'files': agent_hashes},
        'camera': {'source': CAMERA_SOURCE, 'manifestSha256': CAMERA_MANIFEST, 'files': camera_hashes},
        'baselineArtifacts': PINS,
    }
    changes = {CLOUD_FILE: {'before': previous['files'][CLOUD_FILE], 'after': sha(cloud_source)}}
    for role, before_hashes, result in [('agent', agent_hashes, agent_summary), ('camera', camera_hashes, camera_summary)]:
        for name in result['changedFiles']:
            changes[role + '/' + name] = {'before': before_hashes[name], 'after': result['files'][name]}
    dropin = lambda target: ('[Service]\nEnvironment=PYTHONPATH=' + target + '\n').encode()
    artifacts = {
        'cloud.delta.json.gz': gzip.compress(pretty(cloud), mtime=0),
        'agent.source.tar.gz': agent_archive, 'camera.source.tar.gz': camera_archive,
        'baseline-public.json': pretty(baseline_public), 'changed-files.json': pretty(changes),
        'remote-before-public.json': remote_raw,
        'cloud-before-public.json': cloud_remote_raw,
        'agent-transport.conf.template': dropin(agent_summary['newSource']),
        'camera-publisher-transport.conf.template': dropin(camera_summary['newSource']),
    }
    text_diffs = []
    for role, original, expected, permitted in [('agent', agent, agent_hashes, AGENT_CHANGES),
                                               ('camera', camera, camera_hashes, CAMERA_CHANGES)]:
        for name in sorted(permitted):
            if sha(original[name]) != expected[name]:
                text_diffs.append('# ' + role + '/' + name + ': installed before content unavailable locally; use changed-files.json digest pair, never the stale tar as a textual baseline.\n')
                continue
            text_diffs.extend(difflib.unified_diff(original[name].decode().splitlines(True),
                new_contents[name].decode().splitlines(True),
                fromfile=role + '/before/' + name, tofile=role + '/after/' + name))
    artifacts['agent-camera-reviewed-changes.diff'] = ''.join(text_diffs).encode()
    summary = {'format': 1, 'scope': 'read-only-transport-only', 'written': False,
               'cloud': {'oldRelease': C5_RELEASE, 'newRelease': cloud['newRelease'],
                         'manifestSha256': cloud['manifestSha256'], 'changedFiles': [CLOUD_FILE]},
               'agent': agent_summary, 'camera': camera_summary,
               'sdkActions': 0, 'motionCommands': 0, 'newPublicPorts': [], 'databaseMigrations': [],
               'robotChanges': [], 'permissionChanges': [], 'credentialsCopied': False,
               'remoteInventoryVerified': True, 'remoteInventoryCheckedAt': remote['checkedAt'],
               'cloudInventoryVerified': True,
               'readyToApply': False, 'pending': ['fresh-cloud-service-and-unit-check', 'fresh-sdk-disconnected-and-no-active-lease-check', 'reviewed-installer'],
               'artifacts': {name: {'sha256': sha(raw), 'bytes': len(raw)} for name, raw in artifacts.items()}}
    summary['candidateDigest'] = sha(canonical(summary))
    artifacts['candidate-summary.json'] = pretty(summary)
    return artifacts, summary


def write_candidate(output, artifacts):
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Candidate directory must not be a symlink')
    if output.exists():
        if not output.is_dir() or {path.name for path in output.iterdir()} != set(artifacts):
            raise ValueError('Frozen artifact differs: candidate directory contents')
        for name, raw in artifacts.items():
            if checked_bytes(output / name) != raw:
                raise ValueError('Frozen artifact differs: ' + name)
        return
    output.mkdir(mode=0o700, parents=True)
    for name, raw in artifacts.items():
        with (output / name).open('xb') as stream:
            stream.write(raw)
        (output / name).chmod(0o600)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true', help='Write local immutable candidate only; never deploy')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    artifacts, summary = prepare_candidate(REPO, BASELINE)
    if args.build:
        output = args.output or WORK / ('transport-candidate-' + summary['candidateDigest'][:16])
        write_candidate(output, artifacts)
        summary = {**summary, 'written': True, 'output': str(output)}
    print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
