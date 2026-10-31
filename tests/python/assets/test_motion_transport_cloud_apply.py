import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / 'tools/operations/apply_motion_transport_cloud.py'


def module():
    assert PATH.is_file(), 'fixed-scope cloud transport installer must exist'
    spec = importlib.util.spec_from_file_location('motion_transport_cloud_apply', PATH)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_transport_cloud_scope_is_one_file_and_never_a_hardware_or_authentication_change():
    value = module()
    assert value.EXPECTED_FILES == {'services/cloud-api/src/control/websocket.js'}
    assert value.RESTART_UNITS == ('thirdhand-stage.service',)
    assert value.OLD == Path('/opt/thirdhand-stage/releases/6187bbbe8ec4d5e8')
    assert value.NEW == Path('/opt/thirdhand-stage/releases/04cc19054caa45a6')


def test_cloud_package_validation_rejects_before_reading_any_unpinned_bundle(tmp_path):
    value = module()
    invalid = tmp_path / 'cloud.delta.json.gz'
    invalid.write_bytes(b'not the reviewed transport package')
    with pytest.raises(ValueError, match='package digest'):
        value.read_package(invalid)


def test_reviewed_cloud_bundle_contains_exactly_the_new_manifest_and_expected_delta():
    value = module()
    # The operational package is intentionally not a dependency of repository CI.
    # Source/manifest invariants below are exercised using a synthetic structure.
    sample = {'format': 1, 'oldRelease': str(value.OLD), 'newRelease': str(value.NEW),
              'oldManifestSha256': value.OLD_MANIFEST,
              'manifestSha256': value.NEW_MANIFEST,
              'changes': {'services/robot/src/server.js': 'eA=='}}
    with pytest.raises(ValueError, match='scope'):
        value.validate_scope(sample)
    sample['changes'] = {'services/cloud-api/src/control/websocket.js': 'eA=='}
    value.validate_scope(sample)
    sample['newRelease'] = '/opt/thirdhand-stage/releases/../../unsafe'
    with pytest.raises(ValueError, match='release'):
        value.validate_scope(sample)


def test_cloud_rollback_target_is_only_the_pinned_existing_release():
    value = module()
    assert value.CURRENT == Path('/opt/thirdhand-stage/current')
    assert value.OLD.parent == value.NEW.parent == value.CURRENT.parent / 'releases'
    assert value.ROOT == Path('/var/backups/thirdhand/access-C3c-transport-20261031')


def test_release_copy_rejects_unlisted_files_instead_of_copying_unknown_material(tmp_path, monkeypatch):
    value = module()
    release = tmp_path / 'releases' / 'old'
    release.mkdir(parents=True)
    monkeypatch.setattr(value, 'OLD', release)
    source = b'public fixture source'
    (release / 'source.js').write_bytes(source)
    manifest = json.dumps({'files': {'source.js': value.sha(source)}}).encode()
    (release / 'manifest.json').write_bytes(manifest)
    assert value.check_release(release, value.sha(manifest))['files']['source.js'] == value.sha(source)
    (release / 'unexpected.env').write_text('synthetic unlisted material')
    with pytest.raises(ValueError, match='inventory'):
        value.check_release(release, value.sha(manifest))


@pytest.mark.parametrize('missing_upload', [True, False])
def test_rollback_restores_verified_old_release_even_if_new_files_or_package_are_lost(monkeypatch, missing_upload):
    value = module()
    calls = []
    class Directory:
        def resolve(self): return self
        def is_dir(self): return True
        def is_symlink(self): return False
        def __truediv__(self, name): return Path('synthetic-backup') / name
    directory = Directory()
    monkeypatch.setattr(value, 'ROOT', directory)
    monkeypatch.setattr(value, 'CURRENT', SimpleNamespace(is_symlink=lambda: True, resolve=lambda: value.NEW))
    monkeypatch.setattr(value, 'os', SimpleNamespace(name='posix', geteuid=lambda: 0, umask=lambda _: None))

    def installed(root, digest):
        calls.append(('check', root))
        if root == value.NEW:
            raise ValueError('Synthetic broken new release')
        return {'files': {}}

    def missing_package(_):
        if missing_upload:
            raise FileNotFoundError('Synthetic lost upload package')
        return {}

    monkeypatch.setattr(value, 'read_package', missing_package)
    monkeypatch.setattr(value, 'check_release', installed)
    monkeypatch.setattr(value, 'active_leases', lambda: calls.append(('leases', 0)))
    monkeypatch.setattr(value, 'switch', lambda target: calls.append(('switch', target)))
    monkeypatch.setattr(value, 'restart', lambda: calls.append(('restart', None)))
    value.main(rollback=True)
    assert ('check', value.OLD) in calls
    assert ('switch', value.OLD) in calls
    assert ('restart', None) in calls
