from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import threading

import cv2
import numpy as np
import pytest

from apps.vision_monitor.main import build_parser, run, validate_args
from thirdhand_va.vision.camera import RegisteredDepthCoverage
from thirdhand_va.vision.preview.local_monitor import run_synchronized_monitor
from thirdhand_va.vision.preview.source import SourceFrame


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RecordingWindow:
    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.close_count = 0

    def show(self, image_rgb: np.ndarray) -> bool:
        self.frames.append(image_rgb.copy())
        return False

    def close(self) -> None:
        self.close_count += 1


def tagged(frame_id: int, image_rgb: np.ndarray) -> SourceFrame:
    return SourceFrame(
        image_rgb,
        received_monotonic_ns=100,
        frame_id=frame_id,
        source_monotonic_ns=90,
        observed_at_ms=80,
    )


class OneFrameSource:
    def __init__(self, frame: SourceFrame) -> None:
        self.frame = frame
        self.open_count = 0
        self.close_count = 0

    @property
    def name(self) -> str:
        return "algorithm"

    def open(self) -> None:
        self.open_count += 1

    def read(self) -> SourceFrame:
        return self.frame

    def close(self) -> None:
        self.close_count += 1


class MatchingDepthReader:
    def __init__(self, frame: SourceFrame) -> None:
        self.frame = frame
        self.requested_ids: list[int] = []
        self.start_count = 0
        self.stop_count = 0

    def start(self) -> None:
        self.start_count += 1

    def take(self, frame_id: int, *, timeout_s: float) -> SourceFrame | None:
        self.requested_ids.append(frame_id)
        return self.frame if self.frame.frame_id == frame_id else None

    def stop(self) -> None:
        self.stop_count += 1


def test_monitor_defaults_attach_read_only_without_defining_a_listener() -> None:
    args = build_parser().parse_args([])

    assert args.algorithm_url == "http://127.0.0.1:3000/camera_lumos_vision"
    assert args.depth_url == "http://127.0.0.1:3000/camera_xvisio_depth"
    assert args.depth_alpha == 0.35
    assert args.display == ":1"
    assert not hasattr(args, "host")
    assert not hasattr(args, "port")


def test_monitor_requires_both_offline_images_as_a_registered_pair() -> None:
    args = build_parser().parse_args(["--algorithm-image", "/tmp/algorithm.jpg"])

    with pytest.raises(ValueError, match="must be provided together"):
        validate_args(args)


def test_offline_entrypoint_composes_real_images_and_closes_its_window(
    tmp_path: Path,
) -> None:
    algorithm_path = tmp_path / "algorithm.png"
    depth_path = tmp_path / "depth.png"
    assert cv2.imwrite(
        str(algorithm_path),
        np.full((120, 180, 3), (100, 100, 100), np.uint8),
    )
    depth_bgr = np.zeros((120, 180, 3), np.uint8)
    depth_bgr[50:80, 60:100] = (0, 0, 255)
    assert cv2.imwrite(str(depth_path), depth_bgr)
    args = build_parser().parse_args([
        "--algorithm-image",
        str(algorithm_path),
        "--depth-image",
        str(depth_path),
    ])
    window = RecordingWindow()

    exit_code = run(
        validate_args(args),
        threading.Event(),
        window_factory=lambda _name: window,
    )

    assert exit_code == 0
    assert len(window.frames) == 1
    assert window.frames[0][60, 80].tolist() != [100, 100, 100]
    assert window.frames[0][37, 90].tolist() == [255, 255, 0]
    assert window.close_count == 1


def test_offline_size_mismatch_stays_visible_and_closes_the_window(
    tmp_path: Path,
) -> None:
    algorithm_path = tmp_path / "algorithm.png"
    depth_path = tmp_path / "depth.png"
    assert cv2.imwrite(
        str(algorithm_path),
        np.full((120, 180, 3), 90, np.uint8),
    )
    assert cv2.imwrite(
        str(depth_path),
        np.full((60, 90, 3), 120, np.uint8),
    )
    args = validate_args(build_parser().parse_args([
        "--algorithm-image",
        str(algorithm_path),
        "--depth-image",
        str(depth_path),
    ]))
    window = RecordingWindow()

    exit_code = run(
        args,
        threading.Event(),
        window_factory=lambda _name: window,
    )

    assert exit_code == 0
    assert len(window.frames) == 1
    assert np.all(window.frames[0][50, 90] == 90)
    assert np.any(window.frames[0][-30:] != 90)
    assert window.close_count == 1


def test_live_monitor_matches_depth_and_releases_only_owned_readers() -> None:
    algorithm_rgb = np.full((120, 180, 3), 100, np.uint8)
    depth_rgb = np.zeros_like(algorithm_rgb)
    depth_rgb[50:80, 60:100] = (255, 0, 0)
    algorithm = OneFrameSource(tagged(71, algorithm_rgb))
    depth = MatchingDepthReader(tagged(71, depth_rgb))
    window = RecordingWindow()

    exit_code = run_synchronized_monitor(
        lambda: algorithm,
        depth,
        window,
        stop_event=threading.Event(),
        match_timeout_s=0,
        depth_coverage=RegisteredDepthCoverage(
            camera_serial="camera",
            reference_size=(180, 120),
            roi_xyxy=(20, 20, 160, 100),
        ),
    )

    assert exit_code == 0
    assert depth.requested_ids == [71]
    assert window.frames[0][60, 80].tolist() != [100, 100, 100]
    assert window.frames[0][20, 90].tolist() == [255, 255, 0]
    assert algorithm.close_count == 1
    assert depth.start_count == 1
    assert depth.stop_count == 1
    assert window.close_count == 1


def test_vscode_debug_entry_targets_the_ubuntu_x11_monitor() -> None:
    launch = json.loads((PROJECT_ROOT / ".vscode/launch.json").read_text())
    configuration = next(
        item
        for item in launch["configurations"]
        if item.get("name") == "Vision Monitor: Ubuntu Desktop Window"
    )

    assert configuration["type"] == "debugpy"
    assert configuration["module"] == "apps.vision_monitor.main"
    assert configuration["python"].endswith(
        "/envs/thirdhand-groundedsam2/bin/python"
    )
    assert configuration["env"]["DISPLAY"] == ":1"
    assert configuration["env"]["XAUTHORITY"] == "/run/user/1000/gdm/Xauthority"
