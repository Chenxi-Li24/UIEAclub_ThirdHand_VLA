import base64
import gzip
import importlib.util
import json
from pathlib import Path, PurePosixPath

import pytest

spec = importlib.util.spec_from_file_location('sdk_timing_builder', Path(__file__).resolve().parents[3] / 'tools/deploy/build_sdk_timing_candidate.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    files = {name: 'a'*64 for name in builder.CLOUD[:-1]}
    files.update({f'preserved/{i}': 'b'*64 for i in range(4657-len(files))})
    before = builder.pretty({'files': files, 'metadata': 'keep'})
    cloud = tmp_path / 'cloud.json'
    cloud.write_bytes(before)
    monkeypatch.setattr(builder, 'OLD_SHA', builder.sha(before))
    calls = []
    def read_git(command, **kwargs):
        calls.append(command)
        assert command[:2] == ['git', 'show'] and command[2].startswith(builder.SOURCE + ':')
        return command[2].encode()
    monkeypatch.setattr(builder.subprocess, 'check_output', read_git)
    edge = tmp_path / 'edge.json'
    source = (PurePosixPath('/') / 'home' / 'test-user' / builder.EDGE_RELATIVE).as_posix()
    edge.write_text(json.dumps(dict(source=source,
        files={'thirdhand_edge/bound_transport.py': builder.EDGE_BOUND_BEFORE, 'thirdhand_edge/runtime.py': 'c'*64},
        pythonpath=['PYTHONPATH='+source], timingEnabled=False, unitHashes={'known.service': 'd'*64})))
    return cloud, edge, tmp_path / 'out', calls


def test_fixed_git_sources_only_preserve_baselines_and_do_not_include_secrets(inputs):
    cloud, edge, out, calls = inputs
    report = builder.build(cloud, edge, out)
    raw = (out / 'sdk-timing-candidate.json.gz').read_bytes()
    package = json.loads(gzip.decompress(raw))
    assert report['packageSha256'] == builder.sha(raw) and len(calls) == 5
    assert set(package['cloud']['changes']) == set(builder.CLOUD)
    assert set(package['edge']['changes']) == {'thirdhand_edge/'+p for p in builder.EDGE}
    assert report['cloudFileCount'] == 4658
    assert package['edge']['after']['thirdhand_edge/runtime.py'] == 'c'*64
    assert json.loads(base64.b64decode(package['cloud']['manifestBase64']))['metadata'] == 'keep'
    assert report['sdkActions'] == 0 and report['newPorts'] == [] and report['permissions'] == []
    assert not any('.env' in path or 'private' in path or 'xvisio' in path for path in package['cloud']['changes'])


@pytest.mark.parametrize('side', ['cloud', 'edge'])
def test_drifted_active_baseline_is_rejected_before_output(inputs, side):
    cloud, edge, out, _ = inputs
    if side == 'cloud':
        cloud.write_text('{}')
    else:
        v = json.loads(edge.read_text())
        v['source'] += '-different'
        edge.write_text(json.dumps(v))
    with pytest.raises(ValueError, match='changed'):
        builder.build(cloud, edge, out)
    assert not out.exists()
