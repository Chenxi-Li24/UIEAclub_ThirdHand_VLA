import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def route(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('c8_route', ROOT / 'tools/operations/apply_ui_sdk_route.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = b'server {\n listen 443 ssl;\n ssl_verify_client on;\n' + module.ANCHOR + b'\n }\n}\n'
    block = (ROOT / 'deploy/public-access/staging/device/state-location.conf').read_text().encode()
    assert module.sha(block) == module.BLOCK_SHA
    config = tmp_path / 'edge.conf'
    config.write_bytes(raw)
    (tmp_path / 'state-location.conf').write_bytes(block)
    monkeypatch.setattr(module, 'CONFIG', config)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'BEFORE', module.sha(raw))
    monkeypatch.setattr(module, 'AFTER', module.sha(raw.replace(module.ANCHOR, block + module.ANCHOR, 1)))
    monkeypatch.setattr(module, 'validate_reload', lambda: None)
    return module, raw


def test_review_is_readonly_then_apply_and_rollback_without_candidate(route):
    module, raw = route
    assert not module.execute()['applied']
    assert module.CONFIG.read_bytes() == raw
    assert not (module.ROOT / 'edge.before.conf').exists()
    assert module.execute(apply=True)['applied']
    modified = module.CONFIG.read_bytes()
    assert modified.count(b'listen 443 ssl;') == 1 and modified.count(b'ssl_verify_client on;') == 1
    (module.ROOT / 'state-location.conf').unlink()
    assert module.execute(rollback=True)['rolledBack']
    assert module.CONFIG.read_bytes() == raw


def test_source_drift_rejected_before_backup(route):
    module, raw = route
    module.CONFIG.write_bytes(raw + b'# another task\n')
    with pytest.raises(ValueError, match='CONFIG_CHANGED'):
        module.execute(apply=True)
    assert not (module.ROOT / 'edge.before.conf').exists()


def test_nginx_failure_restores_original(route, monkeypatch):
    module, raw = route
    attempts = []
    def reload():
        attempts.append(1)
        if len(attempts) == 1:
            raise subprocess.CalledProcessError(1, 'nginx -t')
    monkeypatch.setattr(module, 'validate_reload', reload)
    with pytest.raises(subprocess.CalledProcessError):
        module.execute(apply=True)
    assert module.CONFIG.read_bytes() == raw and len(attempts) == 2


def test_rollback_preserves_concurrent_edit(route):
    module, raw = route
    module.execute(apply=True)
    changed = module.CONFIG.read_bytes() + b'# concurrent\n'
    module.CONFIG.write_bytes(changed)
    with pytest.raises(ValueError, match='ROLLBACK_CONFIG_CHANGED'):
        module.execute(rollback=True)
    assert module.CONFIG.read_bytes() == changed
