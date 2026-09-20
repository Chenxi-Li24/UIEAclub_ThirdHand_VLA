from __future__ import annotations

import json
from pathlib import Path
import select
import signal
import subprocess
import sys

import cv2
import numpy as np

from apps.vision_preview.main import build_parser
from thirdhand_va.vision.preview import OpenCvMjpegSource


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_json_line(process: subprocess.Popen[str], timeout_s: float) -> dict:
    assert process.stdout is not None
    readable, _, _ = select.select([process.stdout], [], [], timeout_s)
    if not readable:
        stderr = "" if process.stderr is None else process.stderr.read()
        raise AssertionError(f"preview process was not ready: {stderr}")
    return json.loads(process.stdout.readline())


def test_parser_defaults_are_safe_and_attach_only() -> None:
    args = build_parser().parse_args([])

    assert args.primary_url == (
        "http://127.0.0.1:3000/camera_lumos_vision"
    )
    assert args.fallback_url == "http://127.0.0.1:3000/camera_xvisio_raw"
    assert args.replay_image is None
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.reconnect_seconds == 2.0
    assert args.open_timeout_ms == 1500
    assert args.read_timeout_ms == 1500


def test_replay_entrypoint_serves_mjpeg_without_camera(tmp_path: Path) -> None:
    image_path = tmp_path / "preview.png"
    image = np.full((90, 140, 3), (30, 90, 180), dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image)
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "apps.vision_preview.main",
            "--replay-image",
            str(image_path),
            "--port",
            "0",
            "--replay-fps",
            "8",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready = read_json_line(process, 5.0)
        assert ready["type"] == "preview_ready"
        assert ready["source_mode"] == "replay"
        assert ready["read_only"] is True
        assert ready["stream_url"].endswith("/stream.mjpg")
        assert ready["health_url"].endswith("/health")

        source = OpenCvMjpegSource(
            ready["stream_url"],
            open_timeout_ms=1_500,
            read_timeout_ms=1_500,
        )
        source.open()
        try:
            received = source.read()
        finally:
            source.close()
        assert received.image_rgb.shape == (90, 140, 3)

        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=5.0) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5.0)
