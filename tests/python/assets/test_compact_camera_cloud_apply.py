"""C3d cloud installer tests use public synthetic files, never a real service."""
import base64
import contextlib
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    path = ROOT / 'tools/operations/apply_compact_camera_cloud.py'
    assert path.is_file(), 'fixed C3d cloud installer required'
    spec = importlib.util.spec_from_file_location('compact_camera_cloud', path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    for name, value in {'ROOT': tmp_path / 'review', 'OLD': tmp_path / 'releases/old',
                        'NEW': tmp_path / 'releases/new', 'CURRENT': tmp_path / 'current',
                        'ENVIRONMENT': tmp_path / 'private.env', 'SHOWCASE': tmp_path / 'index.html'}.items():
        monkeypatch.setattr(m, name, value)
    m.ROOT.mkdir(); m.OLD.mkdir(parents=True)
    old = {name: ('// old ' + name).encode() for name in m.EXISTING_CHANGES}
    old['keep.js'] = b'// unchanged public source'
    for name, raw in old.items():
        p = m.OLD / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
    digest = lambda raw: hashlib.sha256(raw).hexdigest()
    before = {'files': {name: digest(raw) for name, raw in old.items()}}
    before_raw = json.dumps(before, sort_keys=True).encode(); (m.OLD / 'manifest.json').write_bytes(before_raw)
    changed = {name: ('// new ' + name).encode() for name in m.EXPECTED_FILES}
    after = {'files': {**before['files'], **{name: digest(raw) for name, raw in changed.items()}}}
    after_raw = json.dumps(after, sort_keys=True).encode()
    package = {'format': 1, 'oldRelease': str(m.OLD), 'newRelease': str(m.NEW),
               'oldManifestSha256': digest(before_raw), 'manifestSha256': digest(after_raw),
               'manifestBase64': base64.b64encode(after_raw).decode(),
               'changes': {name: base64.b64encode(raw).decode() for name, raw in changed.items()},
               'beforeHashes': {name: before['files'][name] for name in m.EXISTING_CHANGES}}
    package_path = m.ROOT / 'cloud.delta.json.gz'
    package_path.write_bytes(gzip.compress(json.dumps(package).encode(), mtime=0))
    for name, value in {'PACKAGE_SHA': digest(package_path.read_bytes()), 'OLD_MANIFEST': digest(before_raw),
                        'NEW_MANIFEST': digest(after_raw), 'OLD_FILES_COUNT': len(old)}.items():
        monkeypatch.setattr(m, name, value)
    m.ENVIRONMENT.write_bytes(b'not-a-real-secret'); m.SHOWCASE.write_bytes(b'public showcase')
    calls, state = [], {'current': m.OLD, 'occupied': False, 'failRestart': False}
    monkeypatch.setattr(m, 'require_identity', lambda: None)
    monkeypatch.setattr(m, 'installation_lock', lambda: contextlib.nullcontext())
    def current(): return state['current']
    monkeypatch.setattr(m, 'current_target', current)
    def leases():
        if state['occupied']: raise m.DeploymentError('CONTROL_LEASE_OCCUPIED')
    monkeypatch.setattr(m, 'active_leases', leases)
    def switch(target): calls.append(('switch', target)); state['current'] = target
    monkeypatch.setattr(m, 'switch', switch)
    def restart():
        calls.append(('restart', state['current']))
        if state['failRestart']:
            state['failRestart'] = False
            raise m.DeploymentError('API_RESTART_FAILED')
    monkeypatch.setattr(m, 'restart', restart)
    return m, package, calls, state


def test_review_never_creates_a_release_backup_or_changes_a_service(cloud):
    m, _, calls, _ = cloud
    before = set(m.ROOT.iterdir())
    assert m.execute()['applied'] is False
    assert calls == [] and not m.NEW.exists() and set(m.ROOT.iterdir()) == before


def test_apply_changes_exact_three_existing_and_one_new_file(cloud):
    m, _, calls, _ = cloud
    before_env = m.ENVIRONMENT.read_bytes()
    result = m.execute(apply=True)
    assert result['applied'] is True
    assert m.check_release(m.NEW, m.NEW_MANIFEST)['files']['keep.js'] == m.sha(b'// unchanged public source')
    assert len(m.check_release(m.NEW, m.NEW_MANIFEST)['files']) == m.OLD_FILES_COUNT + 1
    assert calls == [('switch', m.NEW), ('restart', m.NEW)]
    assert m.ENVIRONMENT.read_bytes() == before_env and m.SHOWCASE.read_bytes() == b'public showcase'


@pytest.mark.parametrize('change', ['extra-change', 'missing-new', 'extra-inventory', 'before-hash'])
def test_package_scope_changes_are_rejected_before_writing(cloud, change):
    m, package, calls, _ = cloud
    if change == 'extra-change': package['changes']['services/robot/src/server.js'] = 'eA=='
    if change == 'missing-new': package['changes'].pop(m.ADDED_FILE)
    if change == 'before-hash': package['beforeHashes'][next(iter(m.EXISTING_CHANGES))] = '0' * 64
    if change == 'extra-inventory':
        raw = base64.b64decode(package['manifestBase64']); manifest = json.loads(raw)
        manifest['files']['unreviewed.js'] = '0' * 64
        raw = json.dumps(manifest).encode(); package['manifestBase64'] = base64.b64encode(raw).decode()
        m.NEW_MANIFEST = package['manifestSha256'] = m.sha(raw)
    raw = gzip.compress(json.dumps(package).encode(), mtime=0)
    (m.ROOT / 'cloud.delta.json.gz').write_bytes(raw); m.PACKAGE_SHA = m.sha(raw)
    with pytest.raises(m.DeploymentError): m.execute(apply=True)
    assert calls == [] and not m.NEW.exists() and not (m.ROOT / 'before-public.json').exists()


def test_unknown_old_files_or_candidate_collision_are_never_overwritten(cloud):
    m, _, calls, _ = cloud
    (m.OLD / 'foreign.env').write_bytes(b'synthetic unexpected material')
    with pytest.raises(m.DeploymentError): m.execute(apply=True)
    (m.OLD / 'foreign.env').unlink(); m.NEW.mkdir(); (m.NEW / 'foreign').write_bytes(b'preserve')
    with pytest.raises(m.DeploymentError): m.execute(apply=True)
    assert calls == [] and (m.NEW / 'foreign').read_bytes() == b'preserve'


@pytest.mark.parametrize('lost_upload', [True, False])
def test_rollback_does_not_require_package_or_intact_new_release(cloud, lost_upload):
    m, _, calls, state = cloud
    m.execute(apply=True); calls.clear()
    if lost_upload: (m.ROOT / 'cloud.delta.json.gz').unlink()
    (m.NEW / 'keep.js').write_bytes(b'damaged new release')
    assert m.execute(rollback=True)['rolledBack'] is True
    assert state['current'] == m.OLD and calls == [('switch', m.OLD), ('restart', m.OLD)]


@pytest.mark.parametrize('mode', ['apply', 'rollback'])
def test_mutating_modes_take_the_same_lock_before_any_switch(cloud, monkeypatch, mode):
    m, _, calls, _ = cloud
    if mode == 'rollback': m.execute(apply=True)
    calls.clear()
    @contextlib.contextmanager
    def busy():
        raise m.DeploymentError('INSTALLER_BUSY')
        yield
    monkeypatch.setattr(m, 'installation_lock', busy)
    with pytest.raises(m.DeploymentError, match='INSTALLER_BUSY'): m.execute(**{mode: True})
    assert calls == []


def test_failed_restart_recovers_verified_old_release_and_preserves_new_snapshot(cloud):
    m, _, calls, state = cloud; state['failRestart'] = True
    with pytest.raises(m.DeploymentError) as error: m.execute(apply=True)
    assert error.value.rollback == 'restored'
    assert state['current'] == m.OLD and m.NEW.exists()
    assert calls == [('switch', m.NEW), ('restart', m.NEW), ('switch', m.OLD), ('restart', m.OLD)]


def test_new_lease_after_switch_blocks_restart_and_automatic_rollback(cloud, monkeypatch):
    m, _, calls, state = cloud
    original = m.switch
    def occupied(target): original(target); state['occupied'] = True
    monkeypatch.setattr(m, 'switch', occupied)
    with pytest.raises(m.DeploymentError) as error: m.execute(apply=True)
    assert error.value.rollback == 'blocked' and calls == [('switch', m.NEW)]


def test_unfrozen_constants_fail_closed_before_reading_or_writing(cloud, monkeypatch):
    m, _, calls, _ = cloud; monkeypatch.setattr(m, 'PACKAGE_SHA', None)
    with pytest.raises(m.DeploymentError, match='UNFROZEN_CANDIDATE'): m.execute()
    assert calls == [] and not m.NEW.exists()
