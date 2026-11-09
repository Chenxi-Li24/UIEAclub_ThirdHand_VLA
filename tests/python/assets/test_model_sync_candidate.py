import base64
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('model_sync_builder', Path(__file__).resolve().parents[3] / 'tools/deploy/build_model_sync_candidate.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    files = {name: builder.sha(b'old') for name in builder.FILES}
    files.update({f'preserved/{i}': builder.sha(b'unchanged') for i in range(4652)})
    raw = builder.pretty({'files': files, 'keep': 'metadata'})
    source = tmp_path / 'baseline.json'
    source.write_bytes(raw)
    monkeypatch.setattr(builder, 'BASE_SHA', builder.sha(raw))
    def git(args, **kwargs):
        if 'rev-parse' in args:
            return 'a' * 40
        return b'old' if '^:' in args[-1] else b'new'
    monkeypatch.setattr(builder.subprocess, 'check_output', git)
    return source


def test_fixed_scope_preserves_every_other_file(baseline, tmp_path):
    report = builder.build(baseline, 'source', tmp_path / 'candidate')
    packed = (tmp_path / 'candidate/model-sync-candidate.json.gz').read_bytes()
    payload = json.loads(gzip.decompress(packed))
    cloud = payload['cloud']
    assert builder.sha(packed) == report['packageSha256']
    assert set(cloud['changes']) == set(builder.FILES)
    assert {k for k in cloud['after'] if cloud['after'][k] != cloud['before'][k]} == set(builder.FILES)
    assert len(cloud['after']) == 4658
    manifest = base64.b64decode(cloud['manifestBase64'])
    assert builder.sha(manifest) == report['manifestSha256']
    assert json.loads(manifest)['keep'] == 'metadata'
    assert set(payload) == {'schema', 'purpose', 'sourceCommit', 'cloud'}


def test_changed_baseline_is_rejected(baseline, tmp_path):
    baseline.write_bytes(baseline.read_bytes() + b' ')
    with pytest.raises(ValueError, match='baseline'):
        builder.build(baseline, 'source', tmp_path / 'candidate')
    assert not (tmp_path / 'candidate').exists()


def test_source_parent_drift_is_rejected(baseline, tmp_path, monkeypatch):
    monkeypatch.setattr(builder.subprocess, 'check_output', lambda args, **kwargs: 'a' * 40 if 'rev-parse' in args else b'drift')
    with pytest.raises(ValueError, match='parent'):
        builder.build(baseline, 'source', tmp_path / 'candidate')


def test_noop_candidate_is_rejected(baseline, tmp_path, monkeypatch):
    monkeypatch.setattr(builder.subprocess, 'check_output', lambda args, **kwargs: 'a' * 40 if 'rev-parse' in args else b'old')
    with pytest.raises(ValueError, match='changed set'):
        builder.build(baseline, 'source', tmp_path / 'candidate')
