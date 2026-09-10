from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from vision.geometry import make_transform, rpy_xyz_to_matrix
from vision_models.calibration_capture import CalibrationCaptureError
from vision_models.calibration_targets import CharucoSpec
from vision_models.dual_camera_refit_capture import (
    DualCameraFitObservation,
    append_fit_observation,
    fit_summary,
    load_fit_manifest,
)

TARGET = CharucoSpec(9, 12, 0.015, 0.01125, "DICT_5X5_100")
SEED_ID = "sha256:" + "a" * 64


def _observation(*, offset_x_m: float = 0.0, count: int = 24) -> DualCameraFitObservation:
    objects = np.column_stack(
        (
            np.linspace(0.0, 0.15, count),
            np.linspace(0.0, 0.10, count),
            np.zeros(count),
        )
    )
    d435_pixels = np.column_stack((np.linspace(100, 500, count), np.linspace(80, 400, count)))
    lumos_pixels = np.column_stack((np.linspace(200, 1000, count), np.linspace(180, 1100, count)))
    return DualCameraFitObservation(
        point_ids=tuple(range(count)),
        object_points_m=objects,
        d435_image_points_px=d435_pixels,
        lumos_image_points_px=lumos_pixels,
        t_d435_from_board=make_transform(
            rpy_xyz_to_matrix([0.05, -0.1, 0.03]),
            [offset_x_m, -0.02, 0.65],
        ),
        d435_reprojection_rmse_px=0.35,
        old_candidate_lumos_p95_px=118.7,
    )


def _append(
    root: Path,
    sample_id: str,
    result: DualCameraFitObservation,
    skew: float = 20.0,
) -> Path:
    return append_fit_observation(
        root,
        sample_id=sample_id,
        seed_candidate_id=SEED_ID,
        lumos_jpeg=f"lumos-{sample_id}".encode(),
        d435_jpeg=f"d435-{sample_id}".encode(),
        result=result,
        target=TARGET,
        capture_skew_ms=skew,
    )


@pytest.mark.parametrize(
    ("result", "skew", "message"),
    [
        (_observation(count=23), 20.0, "common points"),
        (replace(_observation(), d435_reprojection_rmse_px=1.51), 20.0, "D435"),
        (_observation(), 100.01, "skew"),
    ],
)
def test_rejects_fit_gates_before_writing_files(
    tmp_path: Path,
    result: DualCameraFitObservation,
    skew: float,
    message: str,
) -> None:
    with pytest.raises(CalibrationCaptureError, match=message):
        _append(tmp_path, "fit-01", result, skew)

    assert list(tmp_path.rglob("*")) == []


def test_rejects_duplicate_pose_before_writing_second_images(tmp_path: Path) -> None:
    _append(tmp_path, "fit-01", _observation())

    with pytest.raises(CalibrationCaptureError, match="distinct"):
        _append(tmp_path, "fit-02", _observation(offset_x_m=0.014))

    assert not (tmp_path / "images/lumos/fit-02.jpg").exists()
    assert not (tmp_path / "images/d435/fit-02.jpg").exists()


def test_persists_content_addressed_fit_evidence_and_phase(tmp_path: Path) -> None:
    for index in range(12):
        _append(
            tmp_path,
            f"fit-{index + 1:02d}",
            _observation(offset_x_m=index * 0.015),
        )
        loaded = load_fit_manifest(
            tmp_path,
            target=TARGET,
            seed_candidate_id=SEED_ID,
        )
        assert loaded is not None
        summary = fit_summary(loaded)
        expected_phase = "fit_ready" if index == 11 else "fit_collect"
        assert summary["phase"] == expected_phase
        assert summary["samples"] == index + 1
        assert summary["required_samples"] == 12

    stored = json.loads(
        (tmp_path / "dual-camera-refit-fit.json").read_text(encoding="utf-8")
    )
    assert stored["purpose"] == "fit"
    assert stored["motion_or_robot_access"] is False
    assert stored["observations"][0]["old_candidate_lumos_p95_px"] == pytest.approx(118.7)
    assert stored["observations"][0]["common_points"] == 24
    assert stored["content_id"].startswith("sha256:")


def test_rejects_tampered_fit_manifest(tmp_path: Path) -> None:
    path = _append(tmp_path, "fit-01", _observation())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["observations"][0]["d435_reprojection_rmse_px"] = 0.9
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CalibrationCaptureError, match="integrity"):
        load_fit_manifest(tmp_path, target=TARGET, seed_candidate_id=SEED_ID)
