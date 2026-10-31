"""Ubuntu installer tests: fake systemd/robot, real local payload and file checks."""
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
_fixture_spec = importlib.util.spec_from_file_location('motion_transport_candidate_fixture',
    ROOT / 'tests/python/assets/test_motion_transport_package.py')
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
candidate = _fixture_module.candidate


@pytest.fixture
def installer(candidate, tmp_path, monkeypatch):
    builder, repo, baseline = candidate
    spec = importlib.util.spec_from_file_location('ubuntu_transport_installer', ROOT / 'tools/operations/apply_motion_transport_ubuntu.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    paths = {
        'CANDIDATE': tmp_path / 'candidate', 'OLD_AGENT': tmp_path / 'old-agent', 'OLD_CAMERA': tmp_path / 'old-camera',
        'NEW_AGENT': tmp_path / 'new-agent', 'NEW_CAMERA': tmp_path / 'new-camera', 'REVIEW': tmp_path / 'review',
        'USER_UNIT_FILE': tmp_path / 'user.service', 'SYSTEM_UNIT_FILE': tmp_path / 'system.service',
        'USER_DROPIN': tmp_path / 'user.service.d/50-C3c-transport.conf',
        'SYSTEM_DROPIN': tmp_path / 'system.service.d/50-C3c-transport.conf',
    }
    for name, value in paths.items(): monkeypatch.setattr(module, name, value)
    for role in ('agent', 'camera'):
        directory = paths['OLD_' + role.upper()] / 'thirdhand_edge'; directory.mkdir(parents=True)
    manifest_receipt = json.loads((baseline / 'C3a-ubuntu-installed-final-public.json').read_text())['files']
    names = [name.removeprefix('agent-source/') for name in manifest_receipt]
    for name in names:
        original = ('# before ' + Path(name).name + '\n').encode()
        (paths['OLD_CAMERA'] / name).write_bytes(original)
        agent_original = b'# installed capture repair\n' if name.endswith('/capture.py') else b'# installed runtime repair\n' if name.endswith('/runtime.py') else original
        (paths['OLD_AGENT'] / name).write_bytes(agent_original)
    paths['USER_UNIT_FILE'].write_bytes(b'original-user-unit\n')
    paths['SYSTEM_UNIT_FILE'].write_bytes(b'original-system-unit\n')
    monkeypatch.setattr(module, 'UNIT_PINS', {'edge': builder.sha(paths['USER_UNIT_FILE'].read_bytes()),
        'camera': builder.sha(paths['SYSTEM_UNIT_FILE'].read_bytes())}, raising=False)
    artifacts, summary = builder.prepare_candidate(repo, baseline)
    summary['agent']['newSource'] = paths['NEW_AGENT'].as_posix()
    summary['camera']['newSource'] = paths['NEW_CAMERA'].as_posix()
    before = json.loads(artifacts['baseline-public.json'])
    before['agent']['source'] = paths['OLD_AGENT'].as_posix()
    before['camera']['source'] = paths['OLD_CAMERA'].as_posix()
    artifacts['baseline-public.json'] = builder.pretty(before)
    artifacts['agent-transport.conf.template'] = ('[Service]\nEnvironment=PYTHONPATH=' + paths['NEW_AGENT'].as_posix() + '\n').encode()
    artifacts['camera-publisher-transport.conf.template'] = ('[Service]\nEnvironment=PYTHONPATH=' + paths['NEW_CAMERA'].as_posix() + '\n').encode()
    summary['artifacts'] = {name: {'sha256': builder.sha(data), 'bytes': len(data)} for name, data in artifacts.items() if name != 'candidate-summary.json'}
    summary.pop('candidateDigest')
    summary['candidateDigest'] = builder.sha(builder.canonical(summary))
    artifacts['candidate-summary.json'] = builder.pretty(summary)
    monkeypatch.setattr(module, 'CANDIDATE_DIGEST', summary['candidateDigest'])
    monkeypatch.setattr(module, 'PINS', {name: builder.sha(artifacts[name]) for name in module.PINS})
    paths['CANDIDATE'].mkdir()
    for name, data in artifacts.items(): (paths['CANDIDATE'] / name).write_bytes(data)
    state = {'sdkConnected': False, 'readOnly': True, 'moving': False}
    commands, fault = [], {'cameraRestart': False, 'connectAfterEdge': False}
    monkeypatch.setattr(module, 'require_identity', lambda: None)
    monkeypatch.setattr(module, 'installation_lock', lambda: contextlib.nullcontext())
    monkeypatch.setattr(module, 'robot_state', lambda: dict(state))
    clock = 1793455200
    monkeypatch.setattr(module, 'now', lambda: clock)
    def inspect(role):
        user = role == 'edge'
        drop = paths['USER_DROPIN' if user else 'SYSTEM_DROPIN']
        return {'FragmentPath': str(paths['USER_UNIT_FILE' if user else 'SYSTEM_UNIT_FILE']),
                'DropInPaths': [str(drop)] if drop.exists() else [], 'ActiveState': 'active',
                'pythonPath': str(paths[('NEW_' if drop.exists() else 'OLD_') + ('AGENT' if user else 'CAMERA')])}
    monkeypatch.setattr(module, 'inspect_unit', inspect)
    def run(arguments):
        commands.append(list(arguments))
        assert not any('tcp-calibration-robot' in value or 'camera-source.service' in value for value in arguments)
        if arguments[:3] == ['sudo', '-n', 'install']:
            if '-d' in arguments: Path(arguments[-1]).mkdir(parents=True, exist_ok=True)
            else: shutil.copyfile(arguments[-2], arguments[-1])
        if arguments[:3] == ['sudo', '-n', 'rm']:
            Path(arguments[-1]).unlink()
        if 'restart' in arguments and arguments[-1] == module.EDGE_UNIT and fault['connectAfterEdge']:
            state['sdkConnected'] = True
        if 'restart' in arguments and arguments[-1] == module.CAMERA_UNIT and fault['cameraRestart']:
            fault['cameraRestart'] = False
            raise module.InstallError('SERVICE_COMMAND_FAILED')
        return ''
    monkeypatch.setattr(module, 'run', run)
    cloud = tmp_path / 'cloud-review.json'
    cloud.write_text(json.dumps({'verified': True, 'currentRelease': module.NEW_CLOUD,
        'deviceId': module.DEVICE_ID, 'activeLeases': 0,
        'checkedAt': datetime.fromtimestamp(clock, timezone.utc).isoformat()}))
    return module, paths, state, commands, fault, cloud, builder.sha(cloud.read_bytes())


def test_review_is_read_only_and_does_not_invent_cloud_clearance(installer):
    module, paths, _, commands, _, _, _ = installer
    result = module.review(module.load_candidate())
    assert result['sdkConnected'] is False and result['cloudReview'] == 'pending'
    assert commands == [] and not paths['REVIEW'].exists()
    assert not paths['NEW_AGENT'].exists() and not paths['USER_DROPIN'].exists()


def test_apply_without_fresh_cloud_clearance_writes_nothing(installer):
    module, paths, _, commands, _, _, _ = installer
    with pytest.raises(module.InstallError): module.apply(module.load_candidate(), None, None)
    assert commands == [] and not paths['REVIEW'].exists()
    assert not paths['NEW_AGENT'].exists() and not paths['NEW_CAMERA'].exists()


def test_known_camera_auto_restart_does_not_block_reviewing_the_fix(installer, monkeypatch):
    module, _, _, commands, _, _, _ = installer
    original = module.inspect_unit
    def restarting(role):
        result = original(role)
        if role == 'camera': result['ActiveState'] = 'activating'
        return result
    monkeypatch.setattr(module, 'inspect_unit', restarting)
    result = module.review(module.load_candidate())
    assert result['units']['camera']['ActiveState'] == 'activating' and commands == []


def test_old_source_drift_or_sdk_connected_stops_before_any_changes(installer):
    module, paths, state, commands, _, _, _ = installer
    state['sdkConnected'] = True
    with pytest.raises(module.InstallError): module.review(module.load_candidate())
    state['sdkConnected'] = False
    (paths['OLD_AGENT'] / 'thirdhand_edge/capture.py').write_bytes(b'changed onsite')
    with pytest.raises(module.InstallError): module.review(module.load_candidate())
    assert commands == [] and not paths['REVIEW'].exists()


def test_original_unit_content_drift_is_rejected_even_if_effective_paths_match(installer):
    module, paths, _, commands, _, _, _ = installer
    paths['USER_UNIT_FILE'].write_bytes(b'another launch with the same reported PYTHONPATH')
    with pytest.raises(module.InstallError): module.review(module.load_candidate())
    assert commands == [] and not paths['REVIEW'].exists()


@pytest.mark.parametrize('name,kind', [('../escape.py', 'file'), ('thirdhand_edge/a.py', 'symlink'),
                                    ('source-manifest.json', 'duplicate'), ('/absolute.py', 'file')])
def test_unsafe_archive_members_are_rejected_without_extraction(installer, name, kind):
    module, *_ = installer
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as archive:
        item = tarfile.TarInfo(name); item.size = 2
        if kind == 'symlink': item.type = tarfile.SYMTYPE; item.linkname = '/outside'
        archive.addfile(item, io.BytesIO(b'{}') if kind != 'symlink' else None)
        if kind == 'duplicate': archive.addfile(item, io.BytesIO(b'{}'))
    with pytest.raises(module.InstallError): module.read_archive(out.getvalue(), 'agent', {})


def test_cloud_review_must_be_fresh_pinned_and_have_no_active_leases(installer):
    module, _, _, _, _, cloud, digest = installer
    assert module.cloud_review(cloud, digest)['activeLeases'] == 0
    with pytest.raises(module.InstallError): module.cloud_review(cloud, '0' * 64)
    value = json.loads(cloud.read_text()); value['checkedAt'] = '2026-10-01T00:00:00+00:00'
    cloud.write_text(json.dumps(value))
    with pytest.raises(module.InstallError): module.cloud_review(cloud, hashlib.sha256(cloud.read_bytes()).hexdigest())


def test_apply_only_adds_two_path_dropins_and_preserves_old_sources_and_units(installer):
    module, paths, _, commands, _, cloud, digest = installer
    payload = module.load_candidate()
    result = module.apply(payload, cloud, digest)
    assert result['applied'] is True
    assert paths['USER_DROPIN'].read_bytes() == payload['templates']['edge']
    assert paths['SYSTEM_DROPIN'].read_bytes() == payload['templates']['camera']
    assert paths['USER_UNIT_FILE'].read_bytes() == b'original-user-unit\n'
    assert paths['SYSTEM_UNIT_FILE'].read_bytes() == b'original-system-unit\n'
    assert len(list((paths['NEW_AGENT'] / 'thirdhand_edge').glob('*.py'))) == 20
    assert paths['REVIEW'].joinpath('before-public.json').is_file()
    assert sum('restart' in command for command in commands) == 2
    assert (paths['OLD_AGENT'] / 'thirdhand_edge/capture.py').read_bytes() == b'# installed capture repair\n'


def test_restart_failure_rolls_back_only_owned_dropins_and_keeps_snapshots(installer):
    module, paths, _, commands, fault, cloud, digest = installer
    fault['cameraRestart'] = True
    with pytest.raises(module.InstallError) as failure:
        module.apply(module.load_candidate(), cloud, digest)
    assert failure.value.rollback == 'restored'
    assert not paths['USER_DROPIN'].exists() and not paths['SYSTEM_DROPIN'].exists()
    assert paths['NEW_AGENT'].exists() and paths['NEW_CAMERA'].exists()
    assert sum('restart' in command for command in commands) == 4


def test_unknown_or_connected_sdk_blocks_further_mutations_and_rollback(installer):
    module, paths, _, commands, fault, cloud, digest = installer
    fault['connectAfterEdge'] = True
    with pytest.raises(module.InstallError) as failure:
        module.apply(module.load_candidate(), cloud, digest)
    assert failure.value.rollback == 'blocked'
    assert paths['USER_DROPIN'].exists() and not paths['SYSTEM_DROPIN'].exists()
    assert sum('restart' in command for command in commands) == 1


def test_rollback_never_removes_an_unexpected_file(installer):
    module, paths, _, commands, _, cloud, digest = installer
    payload = module.load_candidate(); module.apply(payload, cloud, digest)
    paths['SYSTEM_DROPIN'].write_bytes(b'changed by another operator')
    count = len(commands)
    with pytest.raises(module.InstallError): module.rollback(payload, cloud, digest)
    assert paths['USER_DROPIN'].exists() and paths['SYSTEM_DROPIN'].exists()
    assert len(commands) == count


def test_another_installer_finishing_before_the_lock_is_not_rolled_back(installer, monkeypatch):
    module, paths, _, commands, _, cloud, digest = installer
    payload, original_review, calls = module.load_candidate(), module.review, []
    def racing_review(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            for role, item in module.roles().items():
                module.install_source(item['new'], payload['sources'][role])
                item['dropin'].parent.mkdir(parents=True, exist_ok=True)
                item['dropin'].write_bytes(payload['templates'][role])
        return original_review(*args, **kwargs)
    monkeypatch.setattr(module, 'review', racing_review)
    result = module.apply(payload, cloud, digest)
    assert result['alreadyApplied'] is True
    assert paths['USER_DROPIN'].exists() and paths['SYSTEM_DROPIN'].exists()
    assert commands == []


def test_rollback_refuses_an_unexpected_loaded_dropin_before_deleting_any_file(installer, monkeypatch):
    module, paths, _, commands, _, cloud, digest = installer
    payload = module.load_candidate(); module.apply(payload, cloud, digest)
    original = module.inspect_unit
    def foreign(role):
        result = original(role)
        if role == 'camera': result['DropInPaths'].append('/unexpected/foreign.conf')
        return result
    monkeypatch.setattr(module, 'inspect_unit', foreign)
    count = len(commands)
    with pytest.raises(module.InstallError): module.rollback(payload, cloud, digest)
    assert len(commands) == count and paths['USER_DROPIN'].exists() and paths['SYSTEM_DROPIN'].exists()


def test_rollback_completes_reload_after_a_previous_crash_with_dropins_already_removed(installer, monkeypatch):
    module, paths, _, commands, _, cloud, digest = installer
    payload = module.load_candidate(); module.apply(payload, cloud, digest)
    paths['USER_DROPIN'].unlink(); paths['SYSTEM_DROPIN'].unlink(); commands.clear()
    cached, original_inspect, original_run = {'edge': True, 'camera': True}, module.inspect_unit, module.run
    def inspect(role):
        result = original_inspect(role)
        if cached[role]:
            result['DropInPaths'] = [str(module.roles()[role]['dropin'])]
            result['pythonPath'] = str(module.roles()[role]['new'])
        return result
    def run(arguments):
        result = original_run(arguments)
        if 'daemon-reload' in arguments: cached['edge' if '--user' in arguments else 'camera'] = False
        return result
    monkeypatch.setattr(module, 'inspect_unit', inspect); monkeypatch.setattr(module, 'run', run)
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    result = module.rollback(payload, cloud, digest)
    assert result['rolledBack'] is True
    assert sum('restart' in command for command in commands) == 2


def test_explicit_rollback_does_not_require_the_candidate_or_damaged_new_snapshot(installer, monkeypatch):
    module, paths, _, commands, _, cloud, digest = installer
    module.apply(module.load_candidate(), cloud, digest)
    damaged = paths['NEW_AGENT'] / 'thirdhand_edge/runtime.py'
    damaged.chmod(0o600); damaged.write_bytes(b'damaged new snapshot')
    def gone(): raise module.InstallError('CANDIDATE_GONE')
    monkeypatch.setattr(module, 'load_candidate', gone)
    commands.clear()
    assert module.main(['--rollback', '--cloud-review-file', str(cloud), '--cloud-review-sha256', digest]) == 0
    assert not paths['USER_DROPIN'].exists() and not paths['SYSTEM_DROPIN'].exists()
    assert sum('restart' in command for command in commands) == 2


def test_rollback_verifies_old_source_before_withdrawing_any_dropin(installer):
    module, paths, _, commands, _, cloud, digest = installer
    payload = module.load_candidate(); module.apply(payload, cloud, digest)
    (paths['OLD_AGENT'] / 'thirdhand_edge/runtime.py').write_bytes(b'old snapshot damaged')
    count = len(commands)
    with pytest.raises(module.InstallError): module.rollback(payload, cloud, digest)
    assert len(commands) == count and paths['USER_DROPIN'].exists() and paths['SYSTEM_DROPIN'].exists()


def test_unit_content_changed_during_restart_is_not_reported_as_success(installer, monkeypatch):
    module, paths, _, commands, _, cloud, digest = installer
    original = module.run
    def changed(arguments):
        result = original(arguments)
        if 'restart' in arguments and arguments[-1] == module.CAMERA_UNIT:
            paths['USER_UNIT_FILE'].write_bytes(b'external operator changed original unit')
        return result
    monkeypatch.setattr(module, 'run', changed)
    with pytest.raises(module.InstallError) as failure: module.apply(module.load_candidate(), cloud, digest)
    assert failure.value.rollback == 'blocked'
    assert sum('restart' in command for command in commands) == 2


def test_explicit_rollback_rejects_a_held_apply_lock_without_changing_files(installer, monkeypatch, capsys):
    module, paths, _, commands, _, cloud, digest = installer
    module.apply(module.load_candidate(), cloud, digest)
    commands.clear()
    @contextlib.contextmanager
    def busy():
        raise module.InstallError('INSTALLER_BUSY')
        yield
    monkeypatch.setattr(module, 'installation_lock', busy)
    code = module.main(['--rollback', '--cloud-review-file', str(cloud), '--cloud-review-sha256', digest])
    result = json.loads(capsys.readouterr().out)
    assert code == 2 and result['code'] == 'INSTALLER_BUSY'
    assert paths['USER_DROPIN'].exists() and paths['SYSTEM_DROPIN'].exists()
    assert commands == []


@pytest.mark.parametrize('expires_after', ['withdraw', 'daemon-reload', 'first-restart', 'last-restart', 'final-wait'])
def test_rollback_stops_when_clearance_expires_and_can_resume_with_a_fresh_record(installer, monkeypatch, expires_after):
    module, paths, _, commands, _, cloud, digest = installer
    payload = module.load_candidate(); module.apply(payload, cloud, digest); commands.clear()
    clock, cached, expired = {'now': module.now()}, {'edge': True, 'camera': True}, []
    original_inspect, original_run, original_wait = module.inspect_unit, module.run, module.wait_units
    def advance(phase):
        if phase == expires_after and not expired:
            expired.append(True); clock['now'] += 61
    def inspect(role):
        result = original_inspect(role)
        if cached[role]:
            result['DropInPaths'] = [str(module.roles()[role]['dropin'])]
            result['pythonPath'] = str(module.roles()[role]['new'])
        return result
    def run(arguments):
        result = original_run(arguments)
        if 'daemon-reload' in arguments:
            cached['edge' if '--user' in arguments else 'camera'] = False
            advance('daemon-reload')
        if 'restart' in arguments: advance('first-restart' if arguments[-1] == module.EDGE_UNIT else 'last-restart')
        return result
    original_unlink = type(paths['USER_DROPIN']).unlink
    def unlink(path, *args, **kwargs):
        result = original_unlink(path, *args, **kwargs)
        if path == paths['USER_DROPIN']: advance('withdraw')
        return result
    def wait(expected):
        result = original_wait(expected); advance('final-wait'); return result
    monkeypatch.setattr(module, 'now', lambda: clock['now'])
    monkeypatch.setattr(module, 'inspect_unit', inspect); monkeypatch.setattr(module, 'run', run)
    monkeypatch.setattr(module, 'wait_units', wait); monkeypatch.setattr(type(paths['USER_DROPIN']), 'unlink', unlink)
    with pytest.raises(module.InstallError) as error: module.rollback(payload, cloud, digest)
    assert error.value.code == 'CLOUD_REVIEW_STALE' and error.value.rollback == 'blocked'
    expected_restarts = {'withdraw': 0, 'daemon-reload': 0, 'first-restart': 1, 'last-restart': 2, 'final-wait': 2}[expires_after]
    assert sum('restart' in command for command in commands) == expected_restarts
    value = json.loads(cloud.read_text())
    value['checkedAt'] = datetime.fromtimestamp(clock['now'], timezone.utc).isoformat()
    cloud.write_text(json.dumps(value)); fresh_digest = hashlib.sha256(cloud.read_bytes()).hexdigest()
    assert module.rollback(payload, cloud, fresh_digest)['rolledBack'] is True
    assert not paths['USER_DROPIN'].exists() and not paths['SYSTEM_DROPIN'].exists()
    # The new receipt permits re-establishing both old processes. Loaded systemd
    # configuration alone cannot prove a restart completed before interruption.
    assert sum('restart' in command for command in commands) == expected_restarts + 2


def test_rollback_restarts_old_processes_even_when_loaded_config_already_looks_old(installer):
    module, paths, _, commands, _, cloud, digest = installer
    payload = module.load_candidate(); module.apply(payload, cloud, digest)
    paths['USER_DROPIN'].unlink(); paths['SYSTEM_DROPIN'].unlink(); commands.clear()
    # Simulates interruption after daemon-reload but before service restart.
    result = module.rollback(payload, cloud, digest)
    assert result['rolledBack'] is True
    assert sum('restart' in command for command in commands) == 2


@pytest.mark.parametrize('operation', ['review', 'apply', 'rollback'])
@pytest.mark.parametrize('kind', ['regular', 'symlink'])
def test_unloaded_foreign_dropin_on_disk_blocks_every_entry_before_changes(installer, monkeypatch, operation, kind):
    module, paths, _, commands, _, cloud, digest = installer
    payload = module.load_candidate()
    if operation == 'rollback': module.apply(payload, cloud, digest)
    commands.clear()
    directory = paths['SYSTEM_DROPIN'].parent; directory.mkdir(parents=True, exist_ok=True)
    foreign = directory / 'foreign.conf'; foreign.write_bytes(b'unloaded external configuration')
    if kind == 'symlink':
        original = type(foreign).is_symlink
        monkeypatch.setattr(type(foreign), 'is_symlink', lambda path: path == foreign or original(path))
    with pytest.raises(module.InstallError):
        getattr(module, operation)(payload, cloud, digest)
    assert commands == [] and foreign.read_bytes() == b'unloaded external configuration'
    if operation == 'rollback':
        assert paths['USER_DROPIN'].exists() and paths['SYSTEM_DROPIN'].exists()
    else:
        assert not paths['REVIEW'].exists() and not paths['NEW_AGENT'].exists()


def test_unloaded_foreign_dropin_arriving_during_apply_blocks_the_next_restart(installer, monkeypatch):
    module, paths, _, commands, _, cloud, digest = installer
    original = module.run
    def add_foreign(arguments):
        result = original(arguments)
        if 'restart' in arguments and arguments[-1] == module.EDGE_UNIT:
            paths['SYSTEM_DROPIN'].parent.mkdir(parents=True, exist_ok=True)
            paths['SYSTEM_DROPIN'].with_name('foreign.conf').write_bytes(b'external change during maintenance')
        return result
    monkeypatch.setattr(module, 'run', add_foreign)
    with pytest.raises(module.InstallError) as failure: module.apply(module.load_candidate(), cloud, digest)
    assert failure.value.rollback == 'blocked'
    assert sum('restart' in command for command in commands) == 1
    assert paths['USER_DROPIN'].exists() and not paths['SYSTEM_DROPIN'].exists()
