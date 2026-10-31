import importlib.util
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / 'tools/operations/reload_public_tls.py'


def load_script():
    spec = importlib.util.spec_from_file_location('thirdhand_tls_reload', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Exercise the production POSIX branch without requiring the CI runner (or
    # the developer's Windows account) to own files as uid 0.
    module.os = SimpleNamespace(name='posix')
    return module


class PrivateKeyFixture:
    def __init__(self, path, owner):
        self.path, self.owner = path, owner

    def is_file(self):
        return self.path.is_file()

    def is_symlink(self):
        return self.path.is_symlink()

    def stat(self):
        return SimpleNamespace(st_uid=self.owner, st_mode=self.path.stat().st_mode)

    def chmod(self, mode):
        self.path.chmod(mode)

    def __str__(self):
        return str(self.path)


def fixture(tmp_path, *, owner=0):
    cert = tmp_path / 'cert.pem'
    cert.write_text('synthetic public certificate')
    key = tmp_path / 'key.pem'
    key.write_text('synthetic private fixture')
    key.chmod(0o600)
    return [('example.test', cert, PrivateKeyFixture(key, owner))]


def test_invalid_config_keeps_running_nginx_and_never_reloads(tmp_path):
    module = load_script()
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ['/usr/sbin/nginx', '-t']:
            raise subprocess.CalledProcessError(1, argv, stderr=b'private diagnostic')
        return SimpleNamespace(stdout=b'new-cert')
    with pytest.raises(RuntimeError, match='PUBLIC_TLS_RELOAD_FAILED') as exc:
        module.reload_public_tls(fixture(tmp_path), run=run, peer=lambda host: b'old-cert')
    assert 'private diagnostic' not in str(exc.value)
    assert ['/usr/sbin/nginx', '-t'] in calls
    assert not any('systemctl' in c[0] for c in calls)


def test_unchanged_public_leaf_does_not_reload_persistent_wss_workers(tmp_path):
    module = load_script()
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=b'new-cert')
    assert module.reload_public_tls(fixture(tmp_path), run=run, peer=lambda host: b'new-cert') is False
    assert not any('systemctl' in c[0] for c in calls)


def test_changed_leaf_reloads_actual_service_then_verifies_served_certificate(tmp_path):
    module = load_script()
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=b'new-cert')
    def peer(host):
        return b'new-cert' if any(c[:3] == ['/bin/systemctl', 'reload', 'nginx'] for c in calls) else b'old-cert'
    assert module.reload_public_tls(fixture(tmp_path), run=run, peer=peer) is True
    assert sum(c[:3] == ['/bin/systemctl', 'reload', 'nginx'] for c in calls) == 1


def test_nonroot_private_key_owner_is_rejected_before_any_command(tmp_path):
    module = load_script()
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=b'new-cert')
    with pytest.raises(RuntimeError, match='PUBLIC_TLS_RELOAD_FAILED'):
        module.reload_public_tls(fixture(tmp_path, owner=1001), run=run,
                                 peer=lambda host: b'new-cert')
    assert calls == []
