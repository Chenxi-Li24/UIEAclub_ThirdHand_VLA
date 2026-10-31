"""C3d camera-only installer; real files, injected Robot/systemd boundaries."""
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def camera(tmp_path, monkeypatch, private_cloud_review):
    path = ROOT / 'tools/operations/apply_compact_camera_ubuntu.py'
    assert path.is_file(), 'fixed C3d camera installer required'
    spec = importlib.util.spec_from_file_location('compact_camera_ubuntu', path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    for name, value in {'CANDIDATE': tmp_path / 'candidate', 'OLD': tmp_path / 'old', 'NEW': tmp_path / 'new',
                        'REVIEW': tmp_path / 'review', 'UNIT_FILE': tmp_path / 'publisher.service',
                        'DROPIN': tmp_path / 'publisher.service.d/50-C3c-transport.conf'}.items():
        monkeypatch.setattr(m, name, value)
    sha = lambda raw: hashlib.sha256(raw).hexdigest()
    m.CANDIDATE.mkdir(); (m.OLD / 'thirdhand_edge').mkdir(parents=True)
    files = {name: ('# baseline ' + name + '\n').encode() for name in m.EXISTING_CHANGES}
    files.update({'thirdhand_edge/filler%d.py' % n: b'# unchanged\n' for n in range(17)})
    old = {name: sha(raw) for name, raw in files.items()}
    old_manifest = json.dumps({'files': old}, sort_keys=True).encode()
    for name, raw in files.items(): (m.OLD / name).write_bytes(raw)
    (m.OLD / 'source-manifest.json').write_bytes(old_manifest)
    baseline = {'cloud': {}, 'camera': {'source': m.OLD.as_posix(), 'manifestSha256': sha(old_manifest), 'files': old}}
    changed = {name: ('# compact ' + name + '\n').encode() for name in m.EXPECTED_CHANGES}
    after = {**files, **changed}; hashes = {name: sha(raw) for name, raw in after.items()}
    manifest = {'format': 1, 'role': 'camera-compact-candidate', 'automaticSdkConnect': False,
                'files': hashes, 'baselineFiles': old, 'changedFiles': sorted(m.EXPECTED_CHANGES)}
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as tar:
        for name, raw in {**after, 'source-manifest.json': json.dumps(manifest, sort_keys=True).encode()}.items():
            item = tarfile.TarInfo(name); item.size = len(raw); tar.addfile(item, io.BytesIO(raw))
    artifacts = {'camera.source.tar.gz': out.getvalue(), 'baseline-public.json': json.dumps(baseline).encode(),
                 'camera-publisher-compact.conf.template': ('[Service]\nEnvironment=PYTHONPATH=' + m.NEW.as_posix() + '\n').encode()}
    for name, raw in artifacts.items(): (m.CANDIDATE / name).write_bytes(raw)
    monkeypatch.setattr(m, 'PINS', {name: sha(raw) for name, raw in artifacts.items()})
    monkeypatch.setattr(m, 'OLD_MANIFEST', sha(old_manifest))
    monkeypatch.setattr(m, 'NEW_SOURCE_DIGEST', sha(m.canonical(hashes)))
    monkeypatch.setattr(m, 'NEW_CLOUD', '/opt/thirdhand-stage/releases/compact-test')
    m.UNIT_FILE.write_bytes(b'fixed original system camera-publisher unit')
    monkeypatch.setattr(m, 'UNIT_SHA', sha(m.UNIT_FILE.read_bytes()))
    m.DROPIN.parent.mkdir(); m.DROPIN.write_bytes(m.template(m.OLD))
    clock, state, calls = {'now': 1793455200}, {'sdkConnected': False, 'readOnly': True, 'connected': False, 'moving': False}, []
    monkeypatch.setattr(m, 'now', lambda: clock['now'])
    monkeypatch.setattr(m, 'require_identity', lambda: None)
    monkeypatch.setattr(m, 'installation_lock', lambda: contextlib.nullcontext())
    monkeypatch.setattr(m, 'robot_state', lambda: dict(state))
    loaded = {'path': m.OLD}
    def inspect(): return {'FragmentPath': str(m.UNIT_FILE), 'DropInPaths': [str(m.DROPIN)],
                           'pythonPath': str(loaded['path']), 'ActiveState': 'active'}
    monkeypatch.setattr(m, 'inspect_unit', inspect)
    def run(args):
        calls.append(args)
        assert 'thirdhand-stage-edge-read-only.service' not in args and not any('camera-source' in arg or 'robot' in arg.lower() for arg in args)
        if args[:3] == ['sudo', '-n', 'install']: shutil.copyfile(args[-2], args[-1])
        if 'daemon-reload' in args: loaded['path'] = m.NEW if m.DROPIN.read_bytes() == m.template(m.NEW) else m.OLD
        return ''
    monkeypatch.setattr(m, 'run', run)
    receipt = tmp_path / 'cloud-review.json'
    private_cloud_review(m, receipt)
    private_cloud_review(m, m.REVIEW, mode=0o40700)
    def fresh():
        raw = json.dumps({'verified': True, 'currentRelease': m.NEW_CLOUD, 'activeLeases': 0,
                          'deviceId': m.DEVICE_ID, 'checkedAt': datetime.fromtimestamp(clock['now'], timezone.utc).isoformat()}).encode()
        receipt.write_bytes(raw); receipt.chmod(0o600); return sha(raw)
    return m, state, calls, clock, receipt, fresh


def test_camera_review_is_read_only_and_keeps_existing_transport_dropin(camera):
    m, _, calls, _, _, _ = camera
    assert m.review(m.load_candidate())['installed'] is False
    assert calls == [] and not m.REVIEW.exists() and not m.NEW.exists()
    assert m.DROPIN.read_bytes() == m.template(m.OLD)


def test_camera_apply_requires_fresh_cloud_clearance_before_any_write(camera):
    m, _, calls, _, _, _ = camera
    with pytest.raises(m.InstallError): m.apply(m.load_candidate(), None, None)
    assert calls == [] and not m.NEW.exists() and not m.REVIEW.exists()


@pytest.mark.parametrize('metadata', [{'uid': 1001}, {'mode': 0o100644}])
def test_camera_rejects_wrong_receipt_owner_or_public_mode_before_any_write(camera, private_cloud_review, metadata):
    m, _, calls, _, receipt, fresh = camera
    private_cloud_review(m, receipt).update(metadata)
    with pytest.raises(m.InstallError, match='PRIVATE_CLOUD_REVIEW_REQUIRED'):
        m.apply(m.load_candidate(), receipt, fresh())
    assert calls == [] and not m.NEW.exists() and not m.REVIEW.exists()


def test_apply_changes_only_publisher_path_and_restarts_only_publisher(camera):
    m, _, calls, _, receipt, fresh = camera
    result = m.apply(m.load_candidate(), receipt, fresh())
    assert result['applied'] is True and m.DROPIN.read_bytes() == m.template(m.NEW)
    assert len(list((m.NEW / 'thirdhand_edge').glob('*.py'))) == 21
    assert sum('restart' in command for command in calls) == 1
    assert m.UNIT_FILE.read_bytes() == b'fixed original system camera-publisher unit'


@pytest.mark.parametrize('drift', ['old-source', 'unit', 'owned-dropin', 'foreign-dropin', 'foreign-link'])
def test_unknown_changes_block_review_and_apply_without_writing(camera, monkeypatch, drift):
    m, _, calls, _, receipt, fresh = camera
    if drift == 'old-source': (m.OLD / 'thirdhand_edge/filler0.py').write_bytes(b'drift')
    if drift == 'unit': m.UNIT_FILE.write_bytes(b'drift')
    if drift == 'owned-dropin': m.DROPIN.write_bytes(b'drift')
    if drift.startswith('foreign'):
        other = m.DROPIN.with_name('foreign.conf'); other.write_bytes(b'unknown unloaded configuration')
        if drift == 'foreign-link':
            original = type(other).is_symlink
            monkeypatch.setattr(type(other), 'is_symlink', lambda path: path == other or original(path))
    with pytest.raises(m.InstallError): m.apply(m.load_candidate(), receipt, fresh())
    assert calls == [] and not m.NEW.exists() and not m.REVIEW.exists()


def test_candidate_collision_is_preserved(camera):
    m, _, calls, _, receipt, fresh = camera
    m.NEW.mkdir(); (m.NEW / 'foreign').write_bytes(b'preserve')
    with pytest.raises(m.InstallError): m.apply(m.load_candidate(), receipt, fresh())
    assert calls == [] and (m.NEW / 'foreign').read_bytes() == b'preserve'


@pytest.mark.parametrize('kind', ['traversal', 'symlink', 'duplicate', 'extra'])
def test_archive_rejects_unsafe_or_extra_members(camera, kind):
    m, *_ = camera; output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as tar:
        item = tarfile.TarInfo('../escape.py' if kind == 'traversal' else 'thirdhand_edge/bad.py')
        item.size = 1
        if kind == 'symlink': item.type = tarfile.SYMTYPE; item.linkname = '/outside'
        tar.addfile(item, None if kind == 'symlink' else io.BytesIO(b'x'))
        if kind == 'duplicate': tar.addfile(item, io.BytesIO(b'x'))
    with pytest.raises(m.InstallError): m.read_archive(output.getvalue(), {})


def test_rollback_survives_lost_package_and_damaged_new_source(camera):
    m, _, calls, _, receipt, fresh = camera
    m.apply(m.load_candidate(), receipt, fresh()); calls.clear()
    path = m.NEW / 'thirdhand_edge/media_renewal.py'; path.chmod(0o600); path.write_bytes(b'damaged')
    (m.CANDIDATE / 'camera.source.tar.gz').unlink()
    assert m.execute_rollback(receipt, fresh())['rolledBack'] is True
    assert m.DROPIN.read_bytes() == m.template(m.OLD) and sum('restart' in command for command in calls) == 1
    assert m.NEW.exists()


def test_explicit_rollback_takes_apply_lock_and_never_changes_a_busy_installation(camera, monkeypatch):
    m, _, calls, _, receipt, fresh = camera
    m.apply(m.load_candidate(), receipt, fresh()); calls.clear()
    @contextlib.contextmanager
    def busy():
        raise m.InstallError('INSTALLER_BUSY')
        yield
    monkeypatch.setattr(m, 'installation_lock', busy)
    with pytest.raises(m.InstallError, match='INSTALLER_BUSY'): m.execute_rollback(receipt, fresh())
    assert calls == [] and m.DROPIN.read_bytes() == m.template(m.NEW)


@pytest.mark.parametrize('phase', ['write', 'reload', 'restart', 'wait'])
def test_rollback_stops_at_expired_checkpoint_and_resumes_with_fresh_receipt(camera, monkeypatch, phase):
    m, _, calls, clock, receipt, fresh = camera
    m.apply(m.load_candidate(), receipt, fresh()); calls.clear(); expired = []
    original_run, original_wait = m.run, m.wait_unit
    def expire(current):
        if current == phase and not expired: clock['now'] += 61; expired.append(True)
    def run(args):
        result = original_run(args)
        if args[:3] == ['sudo', '-n', 'install']: expire('write')
        if 'daemon-reload' in args: expire('reload')
        if 'restart' in args: expire('restart')
        return result
    def wait(expected): result = original_wait(expected); expire('wait'); return result
    monkeypatch.setattr(m, 'run', run); monkeypatch.setattr(m, 'wait_unit', wait)
    digest = fresh()
    with pytest.raises(m.InstallError) as error: m.execute_rollback(receipt, digest)
    assert error.value.code == 'CLOUD_REVIEW_STALE' and error.value.rollback == 'blocked'
    assert sum('restart' in command for command in calls) == (1 if phase in {'restart', 'wait'} else 0)
    assert m.execute_rollback(receipt, fresh())['rolledBack'] is True


def test_sdk_state_change_blocks_further_configuration_or_restarts(camera, monkeypatch):
    m, state, calls, _, receipt, fresh = camera; original = m.run
    def run(args):
        result = original(args)
        if args[:3] == ['sudo', '-n', 'install']: state['sdkConnected'] = True
        return result
    monkeypatch.setattr(m, 'run', run)
    with pytest.raises(m.InstallError) as error: m.apply(m.load_candidate(), receipt, fresh())
    assert error.value.rollback == 'blocked'
    assert not any('restart' in command for command in calls)


def test_unfrozen_camera_pins_fail_closed(camera, monkeypatch):
    m, _, calls, _, _, _ = camera; monkeypatch.setattr(m, 'NEW_SOURCE_DIGEST', None)
    with pytest.raises(m.InstallError, match='UNFROZEN_CANDIDATE'): m.load_candidate()
    assert calls == [] and not m.REVIEW.exists()


def test_rollback_rejects_a_linked_backup_directory_before_opening_its_lock(camera, monkeypatch):
    m, _, calls, _, receipt, fresh = camera
    m.apply(m.load_candidate(), receipt, fresh()); calls.clear()
    original = type(m.REVIEW).is_symlink
    monkeypatch.setattr(type(m.REVIEW), 'is_symlink', lambda path: path == m.REVIEW or original(path))
    with pytest.raises(m.InstallError, match='UNSAFE_PATH'): m.execute_rollback(receipt, fresh())
    assert calls == [] and m.DROPIN.read_bytes() == m.template(m.NEW)
