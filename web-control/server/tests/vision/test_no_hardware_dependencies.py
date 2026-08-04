from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_IMPORT_ROOTS = {
    "can",
    "pyrealsense2",
    "socket",
    "startouch",
    "subprocess",
    "websocket",
}
FORBIDDEN_ACTION_TOKENS = {
    "adaptive_grasp",
    "command_complete",
    "move_joints",
    "set_gripper",
    "sudo",
}


def test_vision_core_has_no_hardware_process_or_transport_dependencies():
    package = Path(__file__).parents[2] / "vision"
    violations = []
    for path in sorted(package.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".")[0]}
            else:
                roots = set()
            for root in roots & FORBIDDEN_IMPORT_ROOTS:
                violations.append(f"{path.name}: forbidden import {root}")
        lowered = source.lower()
        for token in FORBIDDEN_ACTION_TOKENS:
            if token in lowered:
                violations.append(f"{path.name}: forbidden action token {token}")
    assert violations == []


def test_public_package_import_exposes_only_offline_contracts():
    import vision

    required = {
        "PinholeCamera",
        "SeucmCamera",
        "register_depth_to_lumos",
        "MultiObjectTracker",
        "ObjectMemory",
        "build_dry_run_report",
        "run_replay",
    }
    assert required <= set(vision.__all__)
    assert callable(vision.run_replay)
