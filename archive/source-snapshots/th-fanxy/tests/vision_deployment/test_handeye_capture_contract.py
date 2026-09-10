from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from vision.camera_models import PinholeCamera
from vision_models.calibration_capture import (
    AprilGridSpec,
    CalibrationCaptureError,
    CharucoSpec,
    append_handeye_sample,
    detect_aprilgrid_pose,
    detect_target_pose,
    parse_robot_state,
)
from vision_models.calibration_completion import HandEyeCaptureInput
from vision_models.calibration_pipeline import load_handeye_dataset


def _front_facing_grid(spec: AprilGridSpec) -> np.ndarray:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    board = cv2.aruco.GridBoard(
        (spec.columns, spec.rows),
        180,
        int(round(180 * spec.spacing_ratio)),
        dictionary,
    )
    return board.generateImage((1500, 1500), marginSize=100, borderBits=1)


def _front_facing_charuco(spec: CharucoSpec) -> np.ndarray:
    return spec.board().generateImage((1200, 900), marginSize=40)


def test_aprilgrid_detector_returns_metric_board_pose_and_reprojection() -> None:
    spec = AprilGridSpec(rows=6, columns=6, tag_size_m=0.036, spacing_ratio=0.30)
    image = _front_facing_grid(spec)
    camera_matrix = np.array(
        [[1200.0, 0.0, 750.0], [0.0, 1200.0, 750.0], [0.0, 0.0, 1.0]]
    )

    observation = detect_aprilgrid_pose(
        image,
        spec=spec,
        camera_matrix=camera_matrix,
        distortion_coeffs=np.zeros(4),
    )

    assert observation.detected_points == 144
    assert observation.reprojection_rmse_px < 1.0
    assert observation.t_camera_from_board[2, 3] > 0.1


def test_charuco_detector_returns_metric_board_pose_and_reprojection() -> None:
    spec = CharucoSpec(9, 12, 0.015, 0.01125, "DICT_5X5_100")
    observation = detect_target_pose(
        _front_facing_charuco(spec),
        target=spec,
        camera_matrix=np.array(
            [[1000.0, 0.0, 600.0], [0.0, 1000.0, 450.0], [0.0, 0.0, 1.0]]
        ),
        distortion_coeffs=np.zeros(4),
    )

    assert observation.detected_points == 88
    assert observation.reprojection_rmse_px < 1.0
    assert observation.t_camera_from_board[2, 3] > 0.1


def test_robot_state_parser_is_read_only_strict_and_uses_sdk_rpy_direction() -> None:
    message = {
        "type": "robot_state",
        "joints": [1.0, 20.0, -40.0, 3.0, 4.0, 5.0],
        "velocities": [0.1, -0.1, 0.0, 0.2, 0.1, -0.2],
        "tcpPos": [250.0, -20.0, 310.0],
        "tcpEuler": [10.0, -5.0, 30.0],
        "stateName": "IDLE",
        "ts": 12345,
    }

    state = parse_robot_state(message)

    assert state.timestamp_ms == 12345
    assert state.t_base_from_flange[:3, 3].tolist() == pytest.approx([0.25, -0.02, 0.31])
    assert state.joints_deg == pytest.approx(tuple(message["joints"]))

    moving = dict(message, velocities=[0.0, 0.0, 0.0, 0.0, 0.0, 0.6])
    with pytest.raises(CalibrationCaptureError, match="stationary"):
        parse_robot_state(moving)


def test_handeye_manifest_is_content_addressed_and_assigns_heldout_samples(
    tmp_path: Path,
) -> None:
    spec = AprilGridSpec(rows=6, columns=6, tag_size_m=0.036, spacing_ratio=0.30)
    observation = detect_aprilgrid_pose(
        _front_facing_grid(spec),
        spec=spec,
        camera_matrix=np.array(
            [[1200.0, 0.0, 750.0], [0.0, 1200.0, 750.0], [0.0, 0.0, 1.0]]
        ),
        distortion_coeffs=np.zeros(4),
    )

    for index in range(5):
        distinct_robot = parse_robot_state(
            {
                "type": "robot_state",
                "joints": [1.0 + index, 20.0, -40.0, 3.0, 4.0, 5.0],
                "velocities": [0.0] * 6,
                "tcpPos": [250.0 + 12.0 * index, -20.0, 310.0],
                "tcpEuler": [10.0, -5.0, 30.0],
                "stateName": "IDLE",
                "ts": 12345 + index,
            }
        )
        append_handeye_sample(
            tmp_path,
            sample_id=f"pose-{index + 1:02d}",
            jpeg=b"jpeg payload " + str(index).encode("ascii"),
            robot=distinct_robot,
            observation=observation,
            target=spec,
            camchain_source_id="sha256:" + "a" * 64,
        )

    manifest = json.loads((tmp_path / "handeye.json").read_text(encoding="utf-8"))
    assert manifest["content_id"].startswith("sha256:")
    assert [item["split"] for item in manifest["samples"]] == [
        "fit",
        "fit",
        "fit",
        "fit",
        "validation",
    ]
    assert manifest["motion_command_access"] is False
    assert manifest["robot_state_access"] == "read_only_status"
    assert len(list((tmp_path / "images").glob("*.jpg"))) == 5


def test_handeye_manifest_rejects_repeated_robot_pose(tmp_path: Path) -> None:
    spec = AprilGridSpec(rows=6, columns=6, tag_size_m=0.036, spacing_ratio=0.30)
    robot = parse_robot_state(
        {
            "type": "robot_state",
            "joints": [1.0, 20.0, -40.0, 3.0, 4.0, 5.0],
            "velocities": [0.0] * 6,
            "tcpPos": [250.0, -20.0, 310.0],
            "tcpEuler": [10.0, -5.0, 30.0],
            "stateName": "IDLE",
            "ts": 12345,
        }
    )
    observation = detect_aprilgrid_pose(
        _front_facing_grid(spec),
        spec=spec,
        camera_matrix=np.array(
            [[1200.0, 0.0, 750.0], [0.0, 1200.0, 750.0], [0.0, 0.0, 1.0]]
        ),
        distortion_coeffs=np.zeros(4),
    )
    append_handeye_sample(
        tmp_path,
        sample_id="pose-01",
        jpeg=b"first",
        robot=robot,
        observation=observation,
        target=spec,
        camchain_source_id="sha256:" + "a" * 64,
    )

    with pytest.raises(CalibrationCaptureError, match="distinct|different"):
        append_handeye_sample(
            tmp_path,
            sample_id="pose-02",
            jpeg=b"second",
            robot=robot,
            observation=observation,
            target=spec,
            camchain_source_id="sha256:" + "a" * 64,
        )
    assert not (tmp_path / "images/pose-02.jpg").exists()


def test_capture_module_import_graph_has_no_robot_or_motion_backend() -> None:
    module_path = (
        Path(__file__).parents[2] / "web-control/server/vision_models/calibration_capture.py"
    )
    source = module_path.read_text(encoding="utf-8").lower()
    for forbidden in (
        "startouchclass",
        "singlearm",
        "pyrealsense2",
        "move_joint",
        "move_l",
        "gripper",
    ):
        assert forbidden not in source


def test_handeye_capture_cli_composes_typed_read_only_modules(tmp_path: Path) -> None:
    script_path = Path(__file__).parents[2] / "scripts/vision/capture_handeye_sample.py"
    namespace: dict[str, object] = {
        "__name__": "capture_handeye_sample_test",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), script_path, "exec"), namespace)
    target_path = tmp_path / "target.yaml"
    target_path.write_text(
        "target_type: charuco\nsquaresX: 12\nsquaresY: 9\n"
        "squareLength: 0.015\nmarkerLength: 0.01125\n"
        "dictionary: DICT_5X5_100\n",
        encoding="utf-8",
    )
    spec = namespace["load_target"](target_path)
    camera = HandEyeCaptureInput(
        d435=PinholeCamera(
            fx=1000.0,
            fy=1000.0,
            cx=600.0,
            cy=450.0,
            width=1200,
            height=900,
        ),
        distortion_coeffs=(),
        source_id="sha256:" + "b" * 64,
    )
    robot = parse_robot_state(
        {
            "type": "robot_state",
            "joints": [1.0, 20.0, -40.0, 3.0, 4.0, 5.0],
            "velocities": [0.0] * 6,
            "tcpPos": [250.0, -20.0, 310.0],
            "tcpEuler": [10.0, -5.0, 30.0],
            "stateName": "IDLE",
            "ts": 12345,
        }
    )
    ok, encoded = cv2.imencode(".jpg", _front_facing_charuco(spec))
    assert ok

    manifest = namespace["capture_one"](
        tmp_path / "dataset",
        sample_id="pose-01",
        target=spec,
        calibration=camera,
        jpeg_fetch=lambda _url: encoded.tobytes(),
        robot_read=lambda _url: robot,
        d435_url="http://127.0.0.1:3100/camera_d435_raw",
        robot_url="ws://127.0.0.1:3000/ws",
    )

    assert manifest == tmp_path / "dataset/handeye.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["samples"][0]["detected_points"] == 88
    loaded, source_id = load_handeye_dataset(manifest)
    assert len(loaded) == 1
    assert source_id == payload["content_id"]
    source = script_path.read_text(encoding="utf-8").lower()
    for forbidden in ("startouchclass", "singlearm", "move_joint", "move_l"):
        assert forbidden not in source
