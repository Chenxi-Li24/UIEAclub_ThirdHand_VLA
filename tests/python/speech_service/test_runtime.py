from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "services/speech/src/runtime.py"


def load_module():
    assert MODULE.is_file(), "speech runtime readiness module is missing"
    spec = importlib.util.spec_from_file_location("speech_runtime", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ready_file_is_written_atomically(tmp_path: Path) -> None:
    runtime = load_module()
    target = tmp_path / "speech.ready"
    runtime.write_ready_file(target, {"state": "ERROR"})
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ready"] is True
    assert payload["serviceId"] == "speech"
    assert payload["modelReady"] is False
    assert payload["modelState"] == "ERROR"
    assert not target.with_suffix(".ready.tmp").exists()


def test_ready_payload_distinguishes_listener_from_model() -> None:
    runtime = load_module()
    errored = runtime.readiness_payload({"state": "ERROR"})
    ready = runtime.readiness_payload({"state": "READY"})
    assert errored["ready"] is True
    assert errored["modelReady"] is False
    assert ready["modelReady"] is True


def test_remove_ready_file_is_idempotent(tmp_path: Path) -> None:
    runtime = load_module()
    target = tmp_path / "speech.ready"
    runtime.write_ready_file(target, {"state": "READY"})
    runtime.remove_ready_file(target)
    runtime.remove_ready_file(target)
    assert not target.exists()


def test_voice_server_publishes_and_removes_runtime_readiness() -> None:
    bridge = ROOT / "services/speech/src/voice_bridge.py"
    tree = ast.parse(bridge.read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "runtime"
        for alias in node.names
    }
    called_names = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert {"write_ready_file", "remove_ready_file"} <= imported_names
    assert {"write_ready_file", "remove_ready_file"} <= called_names

