"""C3f uses only public, temporary fixtures; no network or service is invoked."""
import base64
import contextlib
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CAMERA = 'apps/web/public/js/camera-view.js'


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('camera_ui_cloud', ROOT / 'tools/operations/apply_camera_ui_cloud.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    for name, value in {'ROOT': tmp_path / 'review', 'OLD': tmp_path / 'releases/old',
                        'NEW': tmp_path / 'releases/new', 'CURRENT': tmp_path / 'current',
                        'ENVIRONMENT': tmp_path / 'private.env', 'SHOWCASE': tmp_path / 'index.html'}.items():
        monkeypatch.setattr(m, name, value)
    m.ROOT.mkdir(); m.OLD.mkdir(parents=True)
    old = {CAMERA: b'// previous camera', 'services/robot/keep.js': b'// robot unchanged'}
    for name, raw in old.items():
        path = m.OLD / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    digest = lambda raw: hashlib.sha256(raw).hexdigest()
    before = {'format': 1, 'deviceControl': 'explicit-read-only-enrollment', 'files': {name: digest(raw) for name, raw in old.items()}}
    before_raw = json.dumps(before, sort_keys=True).encode(); (m.OLD / 'manifest.json').write_bytes(before_raw)
    changed = {CAMERA: b'// recovered camera'}
    after = {**before, 'files': {**before['files'], CAMERA: digest(changed[CAMERA])}}
    after_raw = json.dumps(after, sort_keys=True).encode()
    monkeypatch.setattr(m, 'NEW', m.OLD.parent / digest(after_raw)[:16])
    package = {'format': 1, 'oldRelease': str(m.OLD), 'newRelease': str(m.NEW),
               'oldManifestSha256': digest(before_raw), 'manifestSha256': digest(after_raw),
               'manifestBase64': base64.b64encode(after_raw).decode(),
               'changes': {name: base64.b64encode(raw).decode() for name, raw in changed.items()},
               'beforeHashes': {CAMERA: before['files'][CAMERA]}}
    package_path = m.ROOT / 'cloud.delta.json.gz'
    package_path.write_bytes(gzip.compress(json.dumps(package).encode(), mtime=0))
    for name, value in {'PACKAGE_SHA': digest(package_path.read_bytes()), 'OLD_MANIFEST': digest(before_raw),
                        'NEW_MANIFEST': digest(after_raw), 'OLD_FILES_COUNT': len(old)}.items():
        monkeypatch.setattr(m, name, value)
    m.ENVIRONMENT.write_bytes(b'synthetic config'); m.SHOWCASE.write_bytes(b'public showcase')
    calls, state = [], {'current': m.OLD, 'occupied': False, 'failRestart': False}
    monkeypatch.setattr(m, 'require_identity', lambda: None)
    monkeypatch.setattr(m, 'installation_lock', lambda: contextlib.nullcontext())
    monkeypatch.setattr(m, 'current_target', lambda: state['current'])
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


def repack(m, package):
    raw = gzip.compress(json.dumps(package).encode(), mtime=0)
    (m.ROOT / 'cloud.delta.json.gz').write_bytes(raw); m.PACKAGE_SHA = m.sha(raw)


def test_default_review_has_zero_writes_and_zero_service_actions(cloud):
    m, _, calls, _ = cloud; before = set(m.ROOT.iterdir())
    result = m.execute()
    assert result['applied'] is False and result['changes'] == [CAMERA]
    assert calls == [] and not m.NEW.exists() and set(m.ROOT.iterdir()) == before


def test_apply_replaces_only_camera_and_preserves_all_other_files_and_metadata(cloud):
    m, _, calls, state = cloud
    before = m.check_release(m.OLD, m.OLD_MANIFEST)
    assert m.execute(apply=True)['applied'] is True
    after = m.check_release(m.NEW, m.NEW_MANIFEST)
    assert after == {**before, 'files': {**before['files'], CAMERA: m.sha(b'// recovered camera')}}
    assert len(after['files']) == len(before['files'])
    assert calls == [('switch', m.NEW), ('restart', m.NEW)] and state['current'] == m.NEW
    assert m.ENVIRONMENT.read_bytes() == b'synthetic config' and m.SHOWCASE.read_bytes() == b'public showcase'


def test_release_is_copied_and_verified_in_staging_before_publishing_candidate(cloud, monkeypatch):
    m, _, _, _ = cloud; copytree = m.shutil.copytree; observed = []
    def copy(source, target, *arguments, **options):
        if source == m.OLD:
            observed.append(target); assert target != m.NEW and not m.NEW.exists()
        return copytree(source, target, *arguments, **options)
    monkeypatch.setattr(m.shutil, 'copytree', copy)
    m.execute(apply=True)
    assert len(observed) == 1 and observed[0].parent == m.NEW.parent and not observed[0].exists()


@pytest.mark.parametrize('change', ['extra-change', 'missing-camera', 'before-hash', 'add-file', 'delete-file', 'unlisted-change', 'metadata-change', 'source-digest'])
def test_repacked_out_of_scope_delta_is_rejected_before_any_write(cloud, change):
    m, package, calls, _ = cloud
    if change == 'extra-change': package['changes']['services/robot/keep.js'] = 'eA=='
    elif change == 'missing-camera': package['changes'].pop(CAMERA)
    elif change == 'before-hash': package['beforeHashes'][CAMERA] = '0' * 64
    elif change == 'source-digest': package['changes'][CAMERA] = 'eA=='
    else:
        manifest = json.loads(base64.b64decode(package['manifestBase64']))
        if change == 'add-file': manifest['files']['unapproved.js'] = '0' * 64
        if change == 'delete-file': manifest['files'].pop('services/robot/keep.js')
        if change == 'unlisted-change': manifest['files']['services/robot/keep.js'] = '0' * 64
        if change == 'metadata-change': manifest['deviceControl'] = 'unapproved'
        raw = json.dumps(manifest).encode(); package['manifestBase64'] = base64.b64encode(raw).decode(); m.NEW_MANIFEST = package['manifestSha256'] = m.sha(raw)
        m.NEW = m.OLD.parent / m.NEW_MANIFEST[:16]; package['newRelease'] = str(m.NEW)
    repack(m, package)
    with pytest.raises(m.DeploymentError): m.execute(apply=True)
    assert not m.NEW.exists() and not (m.ROOT / 'before-public.json').exists() and calls == []


@pytest.mark.parametrize('tamper', ['old-source', 'old-extra', 'candidate-collision', 'current-changed'])
def test_unknown_baseline_or_current_and_candidate_collisions_fail_closed(cloud, tamper):
    m, _, calls, state = cloud
    if tamper == 'old-source': (m.OLD / CAMERA).write_bytes(b'tampered')
    if tamper == 'old-extra': (m.OLD / 'foreign.env').write_bytes(b'not real')
    if tamper == 'candidate-collision': m.NEW.mkdir(); (m.NEW / 'preserve').write_bytes(b'preserve')
    if tamper == 'current-changed': state['current'] = m.OLD.parent / 'foreign'
    with pytest.raises(m.DeploymentError): m.execute(apply=True)
    assert calls == []
    if tamper == 'candidate-collision': assert (m.NEW / 'preserve').read_bytes() == b'preserve'


@pytest.mark.parametrize('damage', ['package-missing', 'candidate-missing', 'candidate-corrupt'])
def test_rollback_requires_only_complete_old_release_and_local_backup(cloud, damage):
    m, _, calls, state = cloud; m.execute(apply=True); calls.clear()
    (m.ROOT / 'cloud.delta.json.gz').unlink()
    if damage == 'candidate-missing': m.shutil.rmtree(m.NEW)
    if damage == 'candidate-corrupt': (m.NEW / CAMERA).write_bytes(b'damaged')
    assert m.execute(rollback=True)['rolledBack'] is True
    assert state['current'] == m.OLD and calls == [('switch', m.OLD), ('restart', m.OLD)]


@pytest.mark.parametrize('mode', ['apply', 'rollback'])
def test_apply_and_rollback_take_the_same_nonblocking_lock(cloud, monkeypatch, mode):
    m, _, calls, _ = cloud
    if mode == 'rollback': m.execute(apply=True)
    calls.clear()
    @contextlib.contextmanager
    def occupied():
        raise m.DeploymentError('INSTALLER_BUSY')
        yield
    monkeypatch.setattr(m, 'installation_lock', occupied)
    with pytest.raises(m.DeploymentError, match='INSTALLER_BUSY'): m.execute(**{mode: True})
    assert calls == []


def test_restart_failure_restores_old_release_without_modifying_environment(cloud):
    m, _, calls, state = cloud; state['failRestart'] = True
    with pytest.raises(m.DeploymentError) as error: m.execute(apply=True)
    assert error.value.rollback == 'restored' and state['current'] == m.OLD
    assert calls == [('switch', m.NEW), ('restart', m.NEW), ('switch', m.OLD), ('restart', m.OLD)]


def test_a_new_lease_after_switch_blocks_both_restart_and_rollback(cloud, monkeypatch):
    m, _, calls, state = cloud; switch = m.switch
    def occupied(target): switch(target); state['occupied'] = True
    monkeypatch.setattr(m, 'switch', occupied)
    with pytest.raises(m.DeploymentError) as error: m.execute(apply=True)
    assert error.value.rollback == 'blocked' and calls == [('switch', m.NEW)]


def test_protected_configuration_change_before_switch_is_not_overwritten(cloud, monkeypatch):
    m, _, calls, _ = cloud; check = m.check_release
    def changed(path, digest):
        value = check(path, digest)
        if path == m.NEW: m.SHOWCASE.write_bytes(b'new external showcase')
        return value
    monkeypatch.setattr(m, 'check_release', changed)
    with pytest.raises(m.DeploymentError): m.execute(apply=True)
    assert calls == [] and m.SHOWCASE.read_bytes() == b'new external showcase'


def test_unfrozen_candidate_is_never_usable(cloud, monkeypatch):
    m, _, calls, _ = cloud; monkeypatch.setattr(m, 'PACKAGE_SHA', None)
    with pytest.raises(m.DeploymentError, match='UNFROZEN_CANDIDATE'): m.execute()
    assert calls == [] and not m.NEW.exists()
