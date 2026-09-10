from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
import yaml
from vision.calibration_gate import sdk_pose_transform
from vision.geometry import make_transform, rpy_xyz_to_matrix
from vision_models.calibration_pipeline import (
    CalibrationPipelineError,
    HandEyeSample,
    load_handeye_dataset,
    load_kalibr_camchain,
    solve_d435_handeye,
)


def _transform(rpy: list[float], xyz: list[float]) -> np.ndarray:
    return make_transform(rpy_xyz_to_matrix(rpy), xyz)


def _camchain(path: Path, *, d435_distortion: str = "none") -> Path:
    t_d435_from_lumos = _transform([0.02, -0.08, 0.03], [0.09, 0.0, 0.11])
    path.write_text(
        yaml.safe_dump(
            {
                "cam0": {
                    "camera_model": "eucm",
                    "intrinsics": [0.679984, 0.747118, 392.59848, 392.44043, 637.39526, 641.77399],
                    "distortion_model": "none",
                    "distortion_coeffs": [],
                    "resolution": [1280, 1280],
                    "rostopic": "/lumos/image_raw",
                },
                "cam1": {
                    "camera_model": "pinhole",
                    "intrinsics": [606.6568, 606.11975, 329.03882, 243.02344],
                    "distortion_model": d435_distortion,
                    "distortion_coeffs": [] if d435_distortion == "none" else [0.1, 0.0, 0.0, 0.0],
                    "resolution": [640, 480],
                    "rostopic": "/d435/image_raw",
                    "T_cn_cnm1": t_d435_from_lumos.tolist(),
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def test_kalibr_camchain_preserves_eucm_and_inverts_documented_extrinsic(tmp_path: Path) -> None:
    calibration = load_kalibr_camchain(_camchain(tmp_path / "camchain.yaml"))

    assert calibration.source_id.startswith("sha256:")
    assert calibration.lumos.alpha == pytest.approx(0.679984)
    assert calibration.lumos.beta == pytest.approx(0.747118)
    assert calibration.d435.width == 640
    assert calibration.runtime_compatible is True
    assert np.allclose(
        calibration.t_lumos_from_d435,
        np.linalg.inv(calibration.t_d435_from_lumos),
    )


def test_kalibr_import_rejects_wrong_camera_order_and_flags_unrectified_d435(
    tmp_path: Path,
) -> None:
    wrong = yaml.safe_load(_camchain(tmp_path / "wrong.yaml").read_text(encoding="utf-8"))
    wrong["cam0"]["camera_model"] = "pinhole"
    (tmp_path / "wrong.yaml").write_text(yaml.safe_dump(wrong), encoding="utf-8")
    with pytest.raises(CalibrationPipelineError, match="cam0.*eucm"):
        load_kalibr_camchain(tmp_path / "wrong.yaml")

    unrectified = load_kalibr_camchain(
        _camchain(tmp_path / "unrectified.yaml", d435_distortion="radtan")
    )
    assert unrectified.runtime_compatible is False
    assert unrectified.reasons == ("d435_runtime_rectification_required",)


def _handeye_samples(*, corrupt_validation: bool = False) -> tuple[HandEyeSample, ...]:
    t_flange_from_d435 = _transform([0.10, -0.20, 0.05], [0.03, 0.02, 0.12])
    t_base_from_board = _transform([0.0, 0.0, 0.0], [0.50, 0.10, 0.0])
    samples = []
    for index in range(14):
        t_base_from_flange = sdk_pose_transform(
            [0.25 + 0.01 * index, -0.10 + 0.02 * index, 0.30 + 0.005 * index],
            [-0.30 + 0.05 * index, 0.20 * math.sin(index), -0.20 + 0.03 * index],
        )
        t_d435_from_board = (
            np.linalg.inv(t_flange_from_d435)
            @ np.linalg.inv(t_base_from_flange)
            @ t_base_from_board
        )
        if corrupt_validation and index == 13:
            t_d435_from_board = np.array(t_d435_from_board, copy=True)
            t_d435_from_board[0, 3] += 0.05
        samples.append(
            HandEyeSample(
                sample_id=f"sample-{index:02d}",
                t_base_from_flange=t_base_from_flange,
                t_d435_from_board=t_d435_from_board,
                board_reprojection_rmse_px=0.25,
                split="fit" if index < 10 else "validation",
            )
        )
    return tuple(samples)


def test_opencv_handeye_uses_correct_rpy_chain_and_heldout_validation() -> None:
    result = solve_d435_handeye(_handeye_samples())

    expected = _transform([0.10, -0.20, 0.05], [0.03, 0.02, 0.12])
    assert np.allclose(result.t_flange_from_d435, expected, atol=1e-7)
    assert result.method in {"PARK", "TSAI", "HORAUD"}
    assert result.fit_samples == 10
    assert result.validation_samples == 4
    assert result.position_p95_m < 1e-7
    assert result.reprojection_rmse_px == pytest.approx(0.25)
    assert result.validated is True
    assert result.reasons == ()


def test_handeye_fails_closed_when_heldout_static_chain_exceeds_gate() -> None:
    result = solve_d435_handeye(_handeye_samples(corrupt_validation=True))

    assert result.validated is False
    assert result.position_p95_m > 0.010
    assert "full_chain_static_p95_too_high" in result.reasons


def test_project_dependency_excludes_opencv_5_python_binding() -> None:
    pyproject = (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"opencv-contrib-python>=4.9,<5"' in pyproject


def _write_handeye_manifest(path: Path) -> Path:
    samples = _handeye_samples()
    records = []
    for sample in samples:
        image = f"image {sample.sample_id}".encode("ascii")
        image_path = path / "images" / f"{sample.sample_id}.jpg"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image)
        records.append(
            {
                "sample_id": sample.sample_id,
                "split": sample.split,
                "image": image_path.relative_to(path).as_posix(),
                "image_sha256": hashlib.sha256(image).hexdigest(),
                "robot_state_timestamp_ms": 1000 + len(records),
                "joints_deg": [1.0, 20.0, -40.0, 3.0, 4.0, 5.0],
                "T_base_from_flange": sample.t_base_from_flange.tolist(),
                "T_d435_from_board": sample.t_d435_from_board.tolist(),
                "detected_tags": 20,
                "board_reprojection_rmse_px": sample.board_reprojection_rmse_px,
            }
        )
    payload = {
        "schema_version": 1,
        "camera": "d435_rgb_raw",
        "camchain_source_id": "sha256:" + "a" * 64,
        "target": {
            "family": "tag36h11",
            "rows": 6,
            "columns": 6,
            "tag_size_m": 0.036,
            "spacing_ratio": 0.30,
        },
        "robot_state_access": "read_only_status",
        "motion_command_access": False,
        "samples": records,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")
    payload["content_id"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    manifest = path / "handeye.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def test_handeye_dataset_loader_checks_content_id_and_image_provenance(tmp_path: Path) -> None:
    manifest = _write_handeye_manifest(tmp_path)

    samples, source_id = load_handeye_dataset(manifest)

    assert len(samples) == 14
    assert len([item for item in samples if item.split == "validation"]) == 4
    assert source_id.startswith("sha256:")

    (tmp_path / "images/sample-00.jpg").write_bytes(b"tampered")
    with pytest.raises(CalibrationPipelineError, match="image provenance"):
        load_handeye_dataset(manifest)
