import base64
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import types

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(relative):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    build = load('tools/deploy/build_login_wait_release.py')
    apply = load('tools/operations/apply_login_wait_cloud.py')
    files = {n: 'a' * 64 for n in build.FILES - build.ADDED}
    files.update({f'preserved/{i}.txt': 'b' * 64 for i in range(4656 - len(files))})
    before = {'format': 1, 'files': files, 'metadata': 'preserve-exactly'}
    raw = (json.dumps(before, sort_keys=True, indent=2) + '\n').encode()
    baseline = tmp_path / 'baseline.json'
    baseline.write_bytes(raw)
    old_sha = build.sha(raw)
    monkeypatch.setattr(build, 'OLD_SHA', old_sha)
    monkeypatch.setattr(build, 'OLD', '/opt/thirdhand-stage/releases/' + old_sha[:16])
    destination = tmp_path / 'candidate'
    report = build.build(baseline, destination, read_source=lambda name: (name + '\n').encode())
    monkeypatch.setattr(apply, 'ROOT', destination)
    monkeypatch.setattr(apply, 'OLD_SHA', old_sha)
    monkeypatch.setattr(apply, 'NEW_SHA', report['manifestSha256'])
    monkeypatch.setattr(apply, 'PACKAGE_SHA', report['packageSha256'])

    def require(condition, error):
        if not condition:
            raise ValueError(error)

    base = apply.configure(types.SimpleNamespace(regular=lambda path, limit: path.read_bytes(),
                                                sha=build.sha, require=require))
    # The real installer is Linux-only; retain Linux release spelling on Windows.
    base.OLD = PurePosixPath(report['oldRelease'])
    base.NEW = PurePosixPath(report['newRelease'])
    return build, apply, base, before, report, destination


def test_only_three_cloud_files_change_and_no_models_device_code_or_credentials(candidate):
    build, apply, base, before, report, destination = candidate
    raw, contents = apply.read_package(base, before)
    assert len(contents) == 3
    assert build.FILES == apply.FILES
    assert report['filesCount'] == 4656 and report['preservedFiles'] == 4653
    assert report['sdkActions'] == 0
    for key in ('databaseMigrations', 'permissionChanges', 'newPublicPorts', 'ubuntuChanges', 'deletedFiles'):
        assert report[key] == []
    assert all(not any(word in n for word in ('edge-agent', 'services/robot', 'xvisio', '.env', 'classic.html', 'classic-source.css', 'assets/')) for n in contents)
    assert json.loads(raw)['metadata'] == before['metadata']


def test_changed_baseline_is_rejected_before_candidate_creation(tmp_path):
    build = load('tools/deploy/build_login_wait_release.py')
    baseline = tmp_path / 'baseline.json'
    baseline.write_text('{}')
    with pytest.raises(ValueError, match='baseline'):
        build.build(baseline, tmp_path / 'candidate')
    assert not (tmp_path / 'candidate').exists()


@pytest.mark.parametrize('attack,expected', [('extra', 'PACKAGE_SCOPE_MISMATCH'), ('bytes', 'NEW_SOURCE_DIGEST_MISMATCH')])
def test_repacked_scope_or_payload_tampering_is_rejected(candidate, monkeypatch, attack, expected):
    build, apply, base, before, report, destination = candidate
    path = destination / 'cloud.delta.json.gz'
    package = json.loads(gzip.decompress(path.read_bytes()))
    name = 'unreviewed.py' if attack == 'extra' else next(iter(package['changes']))
    package['changes'][name] = base64.b64encode(b'changed').decode()
    packed = gzip.compress(json.dumps(package).encode(), mtime=0)
    path.write_bytes(packed)
    monkeypatch.setattr(apply, 'PACKAGE_SHA', build.sha(packed))
    with pytest.raises(ValueError, match=expected):
        apply.read_package(base, before)


def test_corrupt_package_digest_is_rejected(candidate):
    build, apply, base, before, report, destination = candidate
    path = destination / 'cloud.delta.json.gz'
    path.write_bytes(path.read_bytes() + b'corrupt')
    with pytest.raises(ValueError, match='PACKAGE_DIGEST_MISMATCH'):
        apply.read_package(base, before)
