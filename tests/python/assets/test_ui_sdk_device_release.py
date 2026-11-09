import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(relative):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    build = load('tools/deploy/build_ui_sdk_device.py')
    apply = load('tools/operations/apply_ui_sdk_device.py')
    monkeypatch.setattr(apply, 'RETIRED', False)
    originals = {
        'runtime.py': b'def worker(role):\n    box = Outbox(directory / "outbox.sqlite", device_id=device.device_id,)\nroles=("capture", "upload", "control", *(("media",) if media else ()))\nchoices=("control", "capture", "upload", "media")\n',
        'remote-gateway.js': b'const event={sequence:++sourceSequence,receivedAt:now()};\n',
        'telemetry.py': b'# old telemetry\n', 'upload.py': b'# site archive uploader\n',
        'robot-controller.js': b'// site controller\n', 'startouch_bridge.py': b'# site bridge\n',
    }
    baseline = tmp_path / 'baseline'
    baseline.mkdir()
    for name, raw in originals.items():
        (baseline / name).write_bytes(raw)
    monkeypatch.setattr(build, 'BEFORE', {n: build.sha(v) for n, v in originals.items()})
    source = lambda n: (b'from .upload import TelemetryUploadClient\n' if n == 'latest_state.py' else b'# tested ' + n.encode() + b'\n')
    output = tmp_path / 'candidate'
    report = build.build(baseline, output, source=source)
    deployed = tmp_path / 'site'
    for name, raw in originals.items():
        relative = (build.ROBOT if name in ('remote-gateway.js', 'robot-controller.js', 'startouch_bridge.py') else build.AGENT) + name
        path = deployed / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    for key, value in [('BASE', deployed), ('ROOT', output), ('BEFORE', report['beforeHashes']),
                       ('PROTECTED', report['protectedHashes']), ('PACKAGE_SHA', report['packageSha256'])]:
        monkeypatch.setattr(apply, key, value)
    calls = []
    monkeypatch.setattr(apply, 'inactive', lambda: calls.append('inactive'))
    return apply, report, calls


def test_review_preserves_site_and_archive_uploader(candidate):
    apply, report, calls = candidate
    result = apply.execute()
    assert result['applied'] is False and len(result['files']) == 5
    assert calls == []
    assert report['archiveUploaderChanged'] is False
    apply.check(apply.BEFORE)
    apply.check(apply.PROTECTED)
    assert not (apply.ROOT / 'before.json').exists()


def test_active_service_blocks_all_writes(candidate, monkeypatch):
    apply, report, calls = candidate
    def busy():
        raise ValueError('SERVICE_MUST_BE_STOPPED')
    monkeypatch.setattr(apply, 'inactive', busy)
    with pytest.raises(ValueError, match='SERVICE_MUST_BE_STOPPED'):
        apply.execute(apply=True)
    apply.check(apply.BEFORE)
    assert not (apply.ROOT / 'before.json').exists()


def test_apply_and_rollback_preserve_site_policy_even_without_candidate_package(candidate):
    apply, report, calls = candidate
    assert apply.execute(apply=True)['sdkCommands'] == 0
    apply.check(report['afterHashes'])
    apply.check(apply.PROTECTED)
    assert b'from .state_upload import' in (apply.BASE / apply.AGENT / 'latest_state.py').read_bytes()
    (apply.ROOT / 'device.delta.json.gz').write_bytes(b'corrupt')
    assert apply.execute(rollback=True)['rolledBack'] is True
    apply.check(apply.BEFORE)
    apply.check(apply.PROTECTED)


def test_protected_source_drift_blocks_review(candidate):
    apply, report, calls = candidate
    name = next(iter(apply.PROTECTED))
    (apply.BASE / name).write_bytes(b'changed by another task')
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        apply.execute()


def test_partial_write_failure_restores_all_originals(candidate, monkeypatch):
    apply, report, calls = candidate
    original = apply.write
    count = [0]
    def fault(path, raw):
        count[0] += 1
        if count[0] == 2:
            raise OSError('synthetic disk failure')
        original(path, raw)
    monkeypatch.setattr(apply, 'write', fault)
    with pytest.raises(OSError, match='synthetic'):
        apply.execute(apply=True)
    apply.check(apply.BEFORE)
    apply.check(apply.PROTECTED)


def test_retired_candidate_refuses_review_and_apply_but_preserves_rollback(candidate, monkeypatch):
    apply, report, calls = candidate
    apply.execute(apply=True)
    monkeypatch.setattr(apply, 'RETIRED', True)
    for mode in ({}, {'apply': True}):
        with pytest.raises(ValueError, match='C8_CANDIDATE_RETIRED_ACTIVE_SOURCE_MISMATCH'):
            apply.execute(**mode)
    assert apply.execute(rollback=True)['rolledBack'] is True
    apply.check(apply.BEFORE)
