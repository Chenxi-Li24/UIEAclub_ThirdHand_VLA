"""Packaging tests use synthetic public baselines, never deployment secrets."""
import base64
import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / 'tools/operations/prepare_motion_transport_fix.py'
MODULES = ['__init__.py', 'bound_transport.py', 'camera_runtime.py', 'camera_source_gate.py',
           'capture.py', 'command_gate.py', 'frames.py', 'journal.py', 'lease.py',
           'media_publisher.py', 'media_upload.py', 'outbox.py', 'probe.py', 'probe_measurements.py',
           'protocol.py', 'robot_client.py', 'runtime.py', 'telemetry.py', 'transport.py', 'upload.py']


def unpack(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        return {member.name: archive.extractfile(member).read() for member in archive}


@pytest.fixture
def candidate(tmp_path):
    spec = importlib.util.spec_from_file_location('motion_transport_builder', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo, baseline = tmp_path / 'repo', tmp_path / 'baseline'
    repo.mkdir(); baseline.mkdir()
    originals = {'thirdhand_edge/' + name: ('# before ' + name + '\n').encode() for name in MODULES}
    installed = {**originals, 'thirdhand_edge/capture.py': b'# installed capture repair\n',
                 'thirdhand_edge/runtime.py': b'# installed runtime repair\n'}
    installed_hashes = {name: module.sha(raw) for name, raw in installed.items()}
    camera_hashes = {name: module.sha(raw) for name, raw in originals.items()}
    for name, raw in installed.items():
        destination = repo / 'services/edge-agent/src' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b'# candidate ' + name.encode() + b'\n'
                                if name in module.AGENT_CHANGES | module.CAMERA_CHANGES else raw)
    cloud_path = repo / module.CLOUD_FILE
    cloud_path.parent.mkdir(parents=True, exist_ok=True)
    cloud_path.write_bytes(b'// candidate control websocket\n')
    manifest = {'format': 1, 'mode': 'synthetic-read-only-baseline', 'files': {
        module.CLOUD_FILE: module.sha(b'// prior websocket\n'),
        'services/cloud-api/src/device-runtime.js': module.sha(b'unchanged-device-runtime'),
        'services/robot/src/control-policy.js': module.sha(b'unchanged-policy'),
    }}
    manifest_raw = module.pretty(manifest)
    module.C5_MANIFEST = module.sha(manifest_raw)
    cloud = {'archiveSha256': '6187bbbe8ec4d5e8' + '0' * 48,
             'manifestBase64': base64.b64encode(manifest_raw).decode()}
    (baseline / 'C5-history-display.delta.json.gz').write_bytes(gzip.compress(module.pretty(cloud), mtime=0))
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as archive:
        for name, raw in {**originals, 'agent-source-manifest.json': b'{}'}.items():
            info = tarfile.TarInfo(name); info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    (baseline / 'C3a-agent-source.tar.gz').write_bytes(out.getvalue())
    receipt = {'files': {'agent-source/' + name: value for name, value in installed_hashes.items()}}
    (baseline / 'C3a-ubuntu-installed-final-public.json').write_bytes(module.pretty(receipt))
    camera = {'files': {name: base64.b64encode(raw).decode() for name, raw in originals.items()}, 'hashes': camera_hashes}
    payload = base64.b64encode(gzip.compress(module.pretty(camera), mtime=0)).decode()
    (baseline / 'C2i-apply-coalesced.py').write_text("import base64\nv=base64.b64decode(" + repr(payload) + ")\n")
    module.CAMERA_MANIFEST = module.sha(module.canonical(camera_hashes))
    module.PINS = {name: module.sha((baseline / name).read_bytes()) for name in module.PINS}
    remote = {'checkedAt': '2026-10-31T13:02:33+00:00', 'sources': {'agent': installed_hashes, 'camera': camera_hashes},
        'cameraManifestSha256': module.CAMERA_MANIFEST, 'context': {'sdkConnected': False, 'readOnly': True},
        'units': {
            'edge': {'FragmentPath': '/home/nieqingcao/.config/systemd/user/thirdhand-stage-edge-read-only.service',
                     'pythonPath': module.AGENT_SOURCE, 'DropInPaths': '', 'ActiveState': 'active'},
            'camera': {'FragmentPath': '/etc/systemd/system/thirdhand-stage-camera-publisher.service',
                       'pythonPath': module.CAMERA_SOURCE, 'DropInPaths': '', 'ActiveState': 'active'},
        }}
    work = repo / '.superpowers/sdd/2026-10-31-remote-motion-readiness'; work.mkdir(parents=True)
    (work / 'transport-remote-before.json').write_bytes(module.pretty(remote))
    cloud_remote = {'verified': True, 'oldRelease': module.C5_RELEASE, 'manifestSha256': module.C5_MANIFEST,
                    'websocketSha256': manifest['files'][module.CLOUD_FILE], 'activeLeases': 0}
    (work / 'transport-cloud-before.json').write_bytes(module.pretty(cloud_remote))
    module.REPO, module.BASELINE, module.WORK = repo, baseline, work
    return module, repo, baseline


def test_candidate_contains_only_the_allowed_first_batch_runtime_changes(candidate):
    module, repo, baseline = candidate
    artifacts, summary = module.prepare_candidate(repo, baseline)
    assert summary['cloud']['changedFiles'] == ['services/cloud-api/src/control/websocket.js']
    assert set(summary['agent']['changedFiles']) == {'thirdhand_edge/media_upload.py',
        'thirdhand_edge/media_publisher.py', 'thirdhand_edge/upload.py', 'thirdhand_edge/runtime.py'}
    assert set(summary['camera']['changedFiles']) == {'thirdhand_edge/media_upload.py',
        'thirdhand_edge/media_publisher.py', 'thirdhand_edge/camera_runtime.py'}
    assert summary['sdkActions'] == summary['motionCommands'] == 0
    assert summary['newPublicPorts'] == summary['databaseMigrations'] == []
    assert all('robot/' not in name and 'private' not in name for name in artifacts)


def test_snapshots_retain_installed_capture_and_unused_agent_camera_runtime(candidate):
    module, repo, baseline = candidate
    artifacts, summary = module.prepare_candidate(repo, baseline)
    agent = unpack(artifacts['agent.source.tar.gz']); camera = unpack(artifacts['camera.source.tar.gz'])
    receipt = json.loads((baseline / 'C3a-ubuntu-installed-final-public.json').read_text())['files']
    assert module.sha(agent['thirdhand_edge/capture.py']) == receipt['agent-source/thirdhand_edge/capture.py']
    assert module.sha(agent['thirdhand_edge/camera_runtime.py']) == receipt['agent-source/thirdhand_edge/camera_runtime.py']
    assert len([name for name in agent if name.endswith('.py')]) == 20
    assert len([name for name in camera if name.endswith('.py')]) == 20
    before = json.loads(artifacts['baseline-public.json'])
    assert before['agent']['files']['thirdhand_edge/runtime.py'] == receipt['agent-source/thirdhand_edge/runtime.py']
    assert summary['agent']['baselineAuthority'] == 'installed-final-public-receipt'


def test_actual_remote_source_inventory_is_checked_without_becoming_a_live_apply_permit(candidate):
    module, repo, baseline = candidate
    artifacts, summary = module.prepare_candidate(repo, baseline)
    assert summary['remoteInventoryVerified'] is True and summary['readyToApply'] is False
    assert summary['cloudInventoryVerified'] is True
    before = json.loads(artifacts['remote-before-public.json'])
    assert before['context']['sdkConnected'] is False
    assert before['units']['edge']['DropInPaths'] == before['units']['camera']['DropInPaths'] == ''
    hashes = json.loads(artifacts['baseline-public.json'])
    for mutate in [
        lambda value: value['context'].update(sdkConnected=True),
        lambda value: value['units']['edge'].update(DropInPaths='/unexpected/override.conf'),
        lambda value: value['sources']['camera'].update({'thirdhand_edge/frames.py': '0' * 64}),
    ]:
        bad = copy.deepcopy(before); mutate(bad)
        with pytest.raises(ValueError, match='Remote inventory mismatch'):
            module.validate_remote_inventory(bad, hashes['agent']['files'], hashes['camera']['files'])
    cloud = json.loads(artifacts['cloud-before-public.json'])
    for mutate in [lambda value: value.update(activeLeases=1), lambda value: value.update(manifestSha256='0' * 64)]:
        bad = copy.deepcopy(cloud); mutate(bad)
        with pytest.raises(ValueError, match='Cloud inventory mismatch'):
            module.validate_cloud_inventory(bad, hashes['cloud']['files'][module.CLOUD_FILE])


def test_default_review_never_creates_output_or_applies_a_deployment(candidate, tmp_path, capsys):
    module, _, _ = candidate
    output = tmp_path / 'not-created'
    module.main(['--output', str(output)])
    assert json.loads(capsys.readouterr().out)['written'] is False
    assert not output.exists()
    with pytest.raises(SystemExit) as error:
        module.main(['--apply'])
    assert error.value.code != 0


def test_baseline_archive_tampering_is_rejected_before_build(candidate, tmp_path):
    module, repo, _ = candidate
    bad = tmp_path / 'tampered'; bad.mkdir()
    (bad / 'C5-history-display.delta.json.gz').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='Baseline digest mismatch'):
        module.prepare_candidate(repo, bad)


def test_build_is_deterministic_and_does_not_replace_a_changed_frozen_artifact(candidate, tmp_path):
    module, repo, baseline = candidate
    artifacts, summary = module.prepare_candidate(repo, baseline)
    again, second = module.prepare_candidate(repo, baseline)
    assert artifacts == again and summary == second
    identifying = {key: value for key, value in summary.items() if key != 'candidateDigest'}
    assert summary['candidateDigest'] == module.sha(module.canonical(identifying))
    output = tmp_path / 'candidate'
    module.write_candidate(output, artifacts); module.write_candidate(output, artifacts)
    (output / 'baseline-public.json').write_bytes(b'changed-after-freeze')
    with pytest.raises(ValueError, match='Frozen artifact differs'):
        module.write_candidate(output, artifacts)


def test_shared_media_modules_are_read_once_for_both_immutable_snapshots(candidate, monkeypatch):
    module, repo, baseline = candidate
    original, reads = module.checked_bytes, []
    def mutating_source(path):
        raw = original(path)
        if path == repo / 'services/edge-agent/src/thirdhand_edge/media_upload.py':
            reads.append(path)
            return raw + ('# revision seen ' + str(len(reads)) + '\n').encode()
        return raw
    monkeypatch.setattr(module, 'checked_bytes', mutating_source)
    artifacts, _ = module.prepare_candidate(repo, baseline)
    agent, camera = unpack(artifacts['agent.source.tar.gz']), unpack(artifacts['camera.source.tar.gz'])
    assert agent['thirdhand_edge/media_upload.py'] == camera['thirdhand_edge/media_upload.py']
    assert len(reads) == 1
