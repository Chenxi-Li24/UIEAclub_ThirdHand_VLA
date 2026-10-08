"""The relocated CLI talks only to the existing owner; all sockets are fake."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]


def load_cli():
    spec = importlib.util.spec_from_file_location(
        "fixed_tcp_client", ROOT / "apps/fixed_tcp_demo/fixed_tcp_demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(getattr(module, "connect", None)), "CLI must use the existing 3000 owner"
    return module


def test_default_cli_requests_nonexecuting_plan(monkeypatch):
    module = load_cli()
    class FakeSocket:
        def __init__(self):
            self.sent = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def send(self, raw):
            self.sent.append(json.loads(raw))
        def recv(self, timeout):
            return json.dumps({"type": "command_status", "status": "complete",
                               "request_id": self.sent[0]["request_id"]})
    socket = FakeSocket()
    monkeypatch.setattr(module, "connect", lambda *args, **kwargs: socket)
    assert module.main([]) == 0
    assert socket.sent[0]["cmd"] == "fixed_tcp_demo"
    assert socket.sent[0]["execute"] is False


def test_cli_requires_both_execution_flags_before_connect(monkeypatch):
    module = load_cli()
    monkeypatch.setattr(module, "connect", lambda *args, **kwargs: pytest.fail("must not connect"))
    with pytest.raises(SystemExit):
        module.main(["--execute"])


def test_saved_planner_fixture_uses_only_a_fake_arm():
    result = subprocess.run(
        [sys.executable, str(ROOT / "apps/fixed_tcp_demo/test_fixed_tcp_plan.py")],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
