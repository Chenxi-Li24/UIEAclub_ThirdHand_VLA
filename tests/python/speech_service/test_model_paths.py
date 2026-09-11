from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "services/speech/src/model_paths.py"


def load_module():
    assert MODULE.is_file(), "formal speech model path resolver is missing"
    spec = importlib.util.spec_from_file_location("speech_model_paths", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_paths_use_project_local_asset_names() -> None:
    paths = load_module().build_model_paths(ROOT)
    assert paths == {
        "whisper-small": (ROOT / "local/models/asr/medium").resolve(),
        "paraformer-streaming": (ROOT / "local/models/asr/realtime").resolve(),
        "fun-asr-nano": (ROOT / "local/models/asr/high").resolve(),
    }


def test_model_paths_are_absolute_and_inside_project() -> None:
    paths = load_module().build_model_paths(ROOT)
    for path in paths.values():
        assert path.is_absolute()
        path.relative_to(ROOT)


def test_voice_bridge_uses_the_project_model_path_resolver() -> None:
    bridge_path = ROOT / "services/speech/src/voice_bridge.py"
    tree = ast.parse(bridge_path.read_text(encoding="utf-8"))
    imported = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "model_paths"
        and any(alias.name == "build_model_paths" for alias in node.names)
        for node in ast.walk(tree)
    )
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "build_model_paths"
    ]
    assert imported and calls
