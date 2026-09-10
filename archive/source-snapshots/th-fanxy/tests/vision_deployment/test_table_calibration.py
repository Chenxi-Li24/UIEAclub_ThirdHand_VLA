from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from vision.camera_models import PinholeCamera
from vision.geometry import invert_transform, make_transform, rotation_z
from vision_models.calibration_capture import (
    CalibrationTargetObservation,
    CharucoSpec,
    ReadOnlyRobotState,
)
from vision_models.calibration_completion import HandEyeCaptureInput
from vision_models.table_calibration import (
    TableCalibrationSample,
    append_table_sample,
    load_table_dataset,
    solve_table_calibration,
)

SOURCE_ID = "sha256:" + "1" * 64
HANDEYE_ID = "sha256:" + "2" * 64
CALIBRATION_ID = "sha256:" + "3" * 64
BOARD_SIZE_M = (0.18, 0.135)


def _content_id(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _pose(rotation: np.ndarray, translation: list[float]) -> np.ndarray:
    return make_transform(rotation, translation)


def _samples(*, validation_height_m: float = 0.0) -> tuple[TableCalibrationSample, ...]:
    t_flange_from_d435 = _pose(np.eye(3), [0.04, -0.02, 0.10])
    locations = (
        (-0.24, -0.16),
        (0.02, -0.16),
        (0.22, -0.10),
        (-0.20, 0.06),
        (0.04, 0.02),
        (0.24, 0.08),
        (-0.12, 0.18),
        (0.18, 0.20),
    )
    samples = []
    for index, (x, y) in enumerate(locations, start=1):
        z = validation_height_m if index == 8 else 0.0
        t_base_from_board = _pose(rotation_z(0.12 * index), [x, y, z])
        t_base_from_flange = _pose(
            rotation_z(-0.03 * index),
            [0.10 + 0.004 * index, -0.05 + 0.003 * index, 0.30],
        )
        t_d435_from_board = (
            invert_transform(t_flange_from_d435)
            @ invert_transform(t_base_from_flange)
            @ t_base_from_board
        )
        samples.append(
            TableCalibrationSample(
                sample_id=f"table-{index:02d}",
                split="validation" if index % 4 == 0 else "fit",
                t_base_from_flange=t_base_from_flange,
                t_d435_from_board=t_d435_from_board,
                board_reprojection_rmse_px=0.35,
            )
        )
    return tuple(samples)


def test_table_solver_composes_handeye_and_passes_heldout_plane_gate() -> None:
    handeye = _pose(np.eye(3), [0.04, -0.02, 0.10])

    result = solve_table_calibration(
        _samples(),
        t_flange_from_d435=handeye,
        calibration_id=CALIBRATION_ID,
        board_size_m=BOARD_SIZE_M,
    )

    assert result.validated is True
    assert result.reasons == ()
    assert result.normal_base == pytest.approx((0.0, 0.0, 1.0), abs=1e-10)
    assert result.offset_m == pytest.approx(0.0, abs=1e-10)
    assert result.fit_rmse_m < 1e-10
    assert result.validation_p95_m < 1e-10
    assert result.calibration_id == CALIBRATION_ID


def test_table_solver_uses_a_ninth_fit_sample_to_recover_xy_coverage() -> None:
    locations = (
        (0.00, 0.00),
        (0.02, 0.03),
        (0.04, 0.06),
        (0.03, 0.09),
        (0.06, 0.12),
        (0.05, 0.15),
        (0.01, 0.11),
        (0.02, 0.07),
        (0.14, 0.08),
    )
    samples = tuple(
        TableCalibrationSample(
            sample_id=f"table-{index:02d}",
            split="validation" if index % 4 == 0 else "fit",
            t_base_from_flange=np.eye(4),
            t_d435_from_board=_pose(np.eye(3), [x, y, 0.0]),
            board_reprojection_rmse_px=0.35,
        )
        for index, (x, y) in enumerate(locations, start=1)
    )

    result = solve_table_calibration(
        samples,
        t_flange_from_d435=np.eye(4),
        calibration_id=CALIBRATION_ID,
        board_size_m=BOARD_SIZE_M,
    )

    assert result.validated is True
    assert result.fit_samples == 7
    assert result.validation_samples == 2


def test_table_solver_rejects_heldout_board_above_desktop() -> None:
    result = solve_table_calibration(
        _samples(validation_height_m=0.020),
        t_flange_from_d435=_pose(np.eye(3), [0.04, -0.02, 0.10]),
        calibration_id=CALIBRATION_ID,
        board_size_m=BOARD_SIZE_M,
    )

    assert result.validated is False
    assert result.validation_p95_m > 0.008
    assert "table_validation_p95_too_high" in result.reasons


def test_table_manifest_is_content_addressed_and_holds_out_every_fourth_sample(
    tmp_path: Path,
) -> None:
    target = CharucoSpec(9, 12, 0.015, 0.01125, "DICT_5X5_100")
    robot = ReadOnlyRobotState(
        t_base_from_flange=np.eye(4),
        joints_deg=(1.0, 20.0, -40.0, 3.0, 4.0, 5.0),
        timestamp_ms=12345,
    )
    output = tmp_path / "dataset"

    for index in range(1, 9):
        distinct_observation = CalibrationTargetObservation(
            t_camera_from_board=_pose(np.eye(3), [0.025 * index, 0.0, 0.30]),
            detected_points=88,
            reprojection_rmse_px=0.4,
        )
        append_table_sample(
            output,
            sample_id=f"table-{index:02d}",
            jpeg=f"jpeg-{index}".encode("ascii"),
            robot=robot,
            observation=distinct_observation,
            target=target,
            candidate_source_id=SOURCE_ID,
            handeye_result_id=HANDEYE_ID,
        )

    manifest = json.loads((output / "table.json").read_text(encoding="utf-8"))
    dataset = load_table_dataset(output / "table.json")
    assert manifest["content_id"] == dataset.dataset_id
    assert dataset.candidate_source_id == SOURCE_ID
    assert dataset.handeye_result_id == HANDEYE_ID
    assert dataset.board_size_m == pytest.approx(BOARD_SIZE_M)
    assert [sample.split for sample in dataset.samples] == [
        "fit",
        "fit",
        "fit",
        "validation",
        "fit",
        "fit",
        "fit",
        "validation",
    ]
    assert len(list((output / "images").glob("*.jpg"))) == 8


def test_table_manifest_accepts_a_ninth_supplemental_fit_sample(tmp_path: Path) -> None:
    target = CharucoSpec(9, 12, 0.015, 0.01125, "DICT_5X5_100")
    robot = ReadOnlyRobotState(
        t_base_from_flange=np.eye(4),
        joints_deg=(1.0, 20.0, -40.0, 3.0, 4.0, 5.0),
        timestamp_ms=12345,
    )

    for index in range(1, 10):
        append_table_sample(
            tmp_path,
            sample_id=f"table-{index:02d}",
            jpeg=f"jpeg-{index}".encode("ascii"),
            robot=robot,
            observation=CalibrationTargetObservation(
                t_camera_from_board=_pose(np.eye(3), [0.025 * index, 0.0, 0.30]),
                detected_points=88,
                reprojection_rmse_px=0.4,
            ),
            target=target,
            candidate_source_id=SOURCE_ID,
            handeye_result_id=HANDEYE_ID,
        )

    dataset = load_table_dataset(tmp_path / "table.json")
    assert len(dataset.samples) == 9
    assert dataset.samples[-1].split == "fit"


def test_table_manifest_rejects_repeated_robot_and_board_pose(tmp_path: Path) -> None:
    target = CharucoSpec(9, 12, 0.015, 0.01125, "DICT_5X5_100")
    robot = ReadOnlyRobotState(np.eye(4), (1, 20, -40, 3, 4, 5), 12345)
    observation = CalibrationTargetObservation(
        _pose(np.eye(3), [0.0, 0.0, 0.3]), 88, 0.4
    )
    append_table_sample(
        tmp_path,
        sample_id="table-01",
        jpeg=b"first",
        robot=robot,
        observation=observation,
        target=target,
        candidate_source_id=SOURCE_ID,
        handeye_result_id=HANDEYE_ID,
    )

    with pytest.raises(ValueError, match="distinct|different"):
        append_table_sample(
            tmp_path,
            sample_id="table-02",
            jpeg=b"second",
            robot=robot,
            observation=observation,
            target=target,
            candidate_source_id=SOURCE_ID,
            handeye_result_id=HANDEYE_ID,
        )
    assert not (tmp_path / "images/table-02.jpg").exists()


def test_table_capture_cli_uses_typed_read_only_camera_and_robot_inputs(
    tmp_path: Path,
) -> None:
    script_path = Path(__file__).parents[2] / "scripts/vision/capture_table_sample.py"
    namespace: dict[str, object] = {
        "__name__": "capture_table_sample_test",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), script_path, "exec"), namespace)
    target = CharucoSpec(9, 12, 0.015, 0.01125, "DICT_5X5_100")
    image = target.board().generateImage((1200, 900), marginSize=40)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    calibration = HandEyeCaptureInput(
        d435=PinholeCamera(1000.0, 1000.0, 600.0, 450.0, 1200, 900),
        distortion_coeffs=(),
        source_id=SOURCE_ID,
    )
    robot = ReadOnlyRobotState(
        t_base_from_flange=np.eye(4),
        joints_deg=(1.0, 20.0, -40.0, 3.0, 4.0, 5.0),
        timestamp_ms=12345,
    )

    manifest = namespace["capture_one"](
        tmp_path / "dataset",
        sample_id="table-01",
        target=target,
        calibration=calibration,
        handeye_result_id=HANDEYE_ID,
        jpeg_fetch=lambda _url: encoded.tobytes(),
        robot_read=lambda _url: robot,
        d435_url="http://127.0.0.1:3100/camera_d435_raw",
        robot_url="ws://127.0.0.1:3000/ws",
    )

    dataset = load_table_dataset(manifest)
    assert len(dataset.samples) == 1
    assert dataset.samples[0].board_reprojection_rmse_px < 1.0
    source = script_path.read_text(encoding="utf-8").lower()
    for forbidden in ("startouchclass", "singlearm", "move_joint", "move_l", "gripper"):
        assert forbidden not in source


def test_table_dataset_rejects_tampered_retained_image(tmp_path: Path) -> None:
    target = CharucoSpec(9, 12, 0.015, 0.01125, "DICT_5X5_100")
    manifest = append_table_sample(
        tmp_path / "dataset",
        sample_id="table-01",
        jpeg=b"original",
        robot=ReadOnlyRobotState(np.eye(4), (1, 20, -40, 3, 4, 5), 12345),
        observation=CalibrationTargetObservation(
            _pose(np.eye(3), [0.0, 0.0, 0.3]), 88, 0.4
        ),
        target=target,
        candidate_source_id=SOURCE_ID,
        handeye_result_id=HANDEYE_ID,
    )
    (manifest.parent / "images/table-01.jpg").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="image provenance"):
        load_table_dataset(manifest)


def test_table_solver_cli_loads_validated_handeye_and_writes_addressed_result(
    tmp_path: Path,
) -> None:
    script_path = Path(__file__).parents[2] / "scripts/vision/solve_table_dataset.py"
    namespace: dict[str, object] = {
        "__name__": "solve_table_dataset_test",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), script_path, "exec"), namespace)
    handeye_transform = _pose(np.eye(3), [0.04, -0.02, 0.10])
    handeye_payload = {
        "schema_version": 1,
        "dataset_id": "sha256:" + "4" * 64,
        "method": "PARK",
        "T_flange_from_d435": handeye_transform.tolist(),
        "fit_samples": 12,
        "validation_samples": 3,
        "validation": {
            "position_rmse_m": 0.003,
            "position_p95_m": 0.006,
            "reprojection_rmse_px": 0.4,
        },
        "validated": True,
        "reasons": [],
        "audit_payload": {
            "schema_version": 1,
            "dataset_id": "sha256:" + "4" * 64,
            "solver": "opencv_calibrateHandEye_park",
            "T_flange_from_d435": handeye_transform.tolist(),
            "validation": {
                "reprojection_rmse_px": 0.4,
                "position_rmse_m": 0.003,
            },
        },
    }
    handeye_payload["content_id"] = _content_id(handeye_payload)
    handeye_path = tmp_path / "handeye-result.json"
    handeye_path.write_text(json.dumps(handeye_payload), encoding="utf-8")
    target = CharucoSpec(9, 12, 0.015, 0.01125, "DICT_5X5_100")
    table_root = tmp_path / "table-dataset"
    for index, sample in enumerate(_samples(), start=1):
        append_table_sample(
            table_root,
            sample_id=sample.sample_id,
            jpeg=f"table-jpeg-{index}".encode("ascii"),
            robot=ReadOnlyRobotState(
                sample.t_base_from_flange,
                (1, 20, -40, 3, 4, 5),
                12000 + index,
            ),
            observation=CalibrationTargetObservation(
                sample.t_d435_from_board,
                88,
                sample.board_reprojection_rmse_px,
            ),
            target=target,
            candidate_source_id=SOURCE_ID,
            handeye_result_id=handeye_payload["content_id"],
        )
    output = tmp_path / "table-result.json"

    result = namespace["solve_manifest"](
        table_root / "table.json",
        handeye_path,
        output,
        CALIBRATION_ID,
    )

    assert result["validated"] is True
    assert result["validation"]["p95_m"] < 1e-10
    assert result["content_id"] == _content_id(
        {key: value for key, value in result.items() if key != "content_id"}
    )
    assert json.loads(output.read_text(encoding="utf-8")) == result
