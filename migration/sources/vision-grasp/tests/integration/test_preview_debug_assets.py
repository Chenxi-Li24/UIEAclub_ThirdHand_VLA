from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

from thirdhand_va.vision.preview import (
    ImageReplaySource,
    PreviewHttpServer,
    PreviewService,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def named(items: list[dict], name: str) -> dict:
    return next(item for item in items if item.get("name") == name)


def test_vscode_preview_launches_integrated_remote_browser() -> None:
    launch = json.loads((PROJECT_ROOT / ".vscode/launch.json").read_text())
    tasks = json.loads((PROJECT_ROOT / ".vscode/tasks.json").read_text())
    settings = json.loads((PROJECT_ROOT / ".vscode/settings.json").read_text())

    window = named(
        launch["configurations"],
        "Vision Preview: Open Window",
    )
    debug_window = named(
        launch["configurations"],
        "Vision Preview: Open Running Debug Window",
    )
    live_debug = named(
        launch["configurations"],
        "Vision Preview: Debug Live Attach",
    )
    replay_debug = named(
        launch["configurations"],
        "Vision Preview: Debug Replay",
    )
    visualization_debug = named(
        launch["configurations"],
        "Vision Visualization: Debug Bundle",
    )
    relay_task = next(
        item
        for item in tasks["tasks"]
        if item.get("label") == "Vision Preview: Start Relay"
    )

    assert settings["workbench.browser.enableRemoteProxy"] is True
    assert window == {
        "type": "editor-browser",
        "request": "launch",
        "name": "Vision Preview: Open Window",
        "url": "http://127.0.0.1:8765/stream.mjpg",
        "preLaunchTask": "Vision Preview: Start Relay",
    }
    assert debug_window["type"] == "editor-browser"
    assert "preLaunchTask" not in debug_window
    assert live_debug["type"] == "debugpy"
    assert live_debug["module"] == "apps.vision_preview.main"
    assert replay_debug["type"] == "debugpy"
    assert "--replay-image" in replay_debug["args"]
    assert visualization_debug == {
        "name": "Vision Visualization: Debug Bundle",
        "type": "debugpy",
        "request": "launch",
        "program": "${workspaceFolder}/scripts/vision/debug_visualization.py",
        "args": [
            "artifacts/vision/validation/live-bundles/frame_000000",
            "--output",
            "artifacts/vision/debug/depth-fusion.jpg",
        ],
        "cwd": "${workspaceFolder}",
        "console": "integratedTerminal",
        "justMyCode": True,
    }
    assert relay_task["isBackground"] is True
    assert relay_task["args"] == ["-u", "-m", "apps.vision_preview.main"]


def test_vscode_background_matcher_has_required_problem_fields() -> None:
    """Characterize VS Code's minimum semantic problem-pattern contract."""
    tasks = json.loads((PROJECT_ROOT / ".vscode/tasks.json").read_text())
    relay_task = next(
        item
        for item in tasks["tasks"]
        if item.get("label") == "Vision Preview: Start Relay"
    )
    matcher = relay_task["problemMatcher"]
    patterns = matcher["pattern"]
    if isinstance(patterns, dict):
        patterns = [patterns]

    assert patterns
    assert all("file" in pattern and "message" in pattern for pattern in patterns)
    assert any(
        pattern.get("kind") == "file"
        or "line" in pattern
        or "location" in pattern
        for pattern in patterns
    )
    assert matcher["background"]["endsPattern"]


def test_preview_smoke_reads_real_replay_stream(tmp_path: Path) -> None:
    image_path = tmp_path / "preview.png"
    assert cv2.imwrite(
        str(image_path),
        np.full((72, 96, 3), (20, 100, 180), dtype=np.uint8),
    )
    service = PreviewService(
        lambda: ImageReplaySource(image_path, fps=30.0),
        offline_size=(96, 72),
    )
    server = PreviewHttpServer(service, host="127.0.0.1", port=0)
    service.start()
    address = server.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/vision/preview_smoke.py",
                "--url",
                f"http://{address[0]}:{address[1]}/stream.mjpg",
                "--frames",
                "3",
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=5.0,
        )
    finally:
        server.stop()
        service.stop()

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["frames"] == 3
    assert report["width"] == 96
    assert report["height"] == 72
    assert report["measured_fps"] > 0


def test_preview_smoke_help_is_independent() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/vision/preview_smoke.py", "--help"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "--url" in result.stdout
    assert "--frames" in result.stdout
