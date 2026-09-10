#!/usr/bin/env python3
"""Capture one stationary D435 AprilGrid observation plus read-only robot state."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

SERVER_ROOT = Path(__file__).resolve().parents[2] / "web-control" / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from vision_models.calibration_capture import (  # noqa: E402
    CalibrationCaptureError,
    CalibrationTargetSpec,
    ReadOnlyRobotState,
    append_handeye_sample,
    detect_target_pose,
    load_calibration_target,
)
from vision_models.calibration_completion import (  # noqa: E402
    HandEyeCaptureInput,
    load_handeye_capture_input,
)
from vision_models.calibration_read_only import (  # noqa: E402
    loopback_url as _loopback_url,
)
from vision_models.calibration_read_only import (  # noqa: E402
    read_stable_robot_state,
)
from vision_models.read_only_http import fetch_jpeg  # noqa: E402


def load_target(path: Path | str) -> CalibrationTargetSpec:
    return load_calibration_target(path)


def capture_one(
    output: Path | str,
    *,
    sample_id: str,
    target: CalibrationTargetSpec,
    calibration: HandEyeCaptureInput,
    jpeg_fetch: Callable[[str], bytes] = fetch_jpeg,
    robot_read: Callable[[str], ReadOnlyRobotState] = read_stable_robot_state,
    d435_url: str,
    robot_url: str,
) -> Path:
    d435_url = _loopback_url(d435_url, {"http"}, "D435 camera")
    robot_url = _loopback_url(robot_url, {"ws", "wss"}, "robot state")
    jpeg = jpeg_fetch(d435_url)
    encoded = np.frombuffer(jpeg, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise CalibrationCaptureError("D435 JPEG cannot be decoded")
    camera_matrix = np.array(
        [
            [calibration.d435.fx, 0.0, calibration.d435.cx],
            [0.0, calibration.d435.fy, calibration.d435.cy],
            [0.0, 0.0, 1.0],
        ],
        dtype=float,
    )
    observation = detect_target_pose(
        image,
        target=target,
        camera_matrix=camera_matrix,
        distortion_coeffs=np.asarray(calibration.distortion_coeffs, dtype=float),
    )
    if observation.detected_points < 24:
        raise CalibrationCaptureError(
            "hand-eye capture requires at least 24 target points"
        )
    if observation.reprojection_rmse_px > 1.5:
        raise CalibrationCaptureError("target reprojection RMSE exceeds 1.5 px")
    robot = robot_read(robot_url)
    return append_handeye_sample(
        output,
        sample_id=sample_id,
        jpeg=jpeg,
        robot=robot,
        observation=observation,
        target=target,
        camchain_source_id=calibration.source_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("configs/vision/calibration/charuco_12x9.yaml"),
    )
    parser.add_argument("--d435-url", default="http://127.0.0.1:3100/camera_d435_raw")
    parser.add_argument("--robot-url", default="ws://127.0.0.1:3000/ws")
    arguments = parser.parse_args()
    manifest = capture_one(
        arguments.output,
        sample_id=arguments.sample_id,
        target=load_target(arguments.target),
        calibration=load_handeye_capture_input(arguments.candidate),
        d435_url=arguments.d435_url,
        robot_url=arguments.robot_url,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    sample = payload["samples"][-1]
    print(
        f"sample={sample['sample_id']} split={sample['split']} "
        f"points={sample['detected_points']} "
        f"reprojection_rmse_px={sample['board_reprojection_rmse_px']:.3f}"
    )
    print(f"manifest={manifest} content_id={payload['content_id']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CalibrationCaptureError as error:
        raise SystemExit(f"hand-eye capture rejected: {error}") from error
