from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.geometry import make_transform, rpy_xyz_to_matrix
from vision_models.calibration_capture import CalibrationCaptureError
from vision_models.dual_camera_candidate import (
    DualCameraCandidate,
    load_dual_camera_candidate,
)
from vision_models.dual_camera_refit_capture import DualCameraFitObservation
from vision_models.dual_camera_refit_solver import (
    solve_dual_camera_refit,
    write_refit_candidate,
)


def _record(item: DualCameraFitObservation, index: int) -> dict[str, object]:
    return {
        "sample_id": f"fit-{index + 1:02d}",
        "point_ids": list(item.point_ids),
        "object_points_m": item.object_points_m.tolist(),
        "d435_image_points_px": item.d435_image_points_px.tolist(),
        "lumos_image_points_px": item.lumos_image_points_px.tolist(),
        "T_d435_from_board": item.t_d435_from_board.tolist(),
        "d435_reprojection_rmse_px": item.d435_reprojection_rmse_px,
        "old_candidate_lumos_p95_px": item.old_candidate_lumos_p95_px,
    }


def _synthetic_problem() -> tuple[
    dict[str, object],
    DualCameraCandidate,
    np.ndarray,
    dict[str, object],
]:
    rng = np.random.default_rng(728)
    d435 = PinholeCamera(606.6568, 606.1198, 329.0388, 243.0234, 640, 480)
    lumos = SeucmCamera(392.5985, 392.4404, 637.3953, 641.7740, 0.679984, 0.747118, 1280, 1280)
    truth = make_transform(
        rpy_xyz_to_matrix([0.027, -0.010, -0.002]),
        [-0.032, -0.046, -0.010],
    )
    seed = make_transform(
        rpy_xyz_to_matrix([0.045, -0.025, 0.012]),
        [-0.022, -0.052, -0.003],
    )
    candidate = DualCameraCandidate(
        candidate_id="sha256:" + "a" * 64,
        provenance="legacy_seed",
        t_lumos_from_d435=seed,
        d435=d435,
        lumos=lumos,
    )
    xs, ys = np.meshgrid(np.arange(1, 11) * 0.015, np.arange(1, 8) * 0.015)
    objects = np.column_stack((xs.reshape(-1), ys.reshape(-1), np.zeros(xs.size)))
    observations = []
    for index in range(12):
        board_pose = make_transform(
            rpy_xyz_to_matrix(
                [
                    -0.12 + 0.025 * (index % 4),
                    -0.10 + 0.04 * (index // 4),
                    -0.08 + 0.016 * index,
                ]
            ),
            [
                -0.08 + 0.04 * (index % 4),
                -0.06 + 0.06 * (index // 4),
                0.58 + 0.025 * (index % 3),
            ],
        )
        points_d435 = objects @ board_pose[:3, :3].T + board_pose[:3, 3]
        points_lumos = points_d435 @ truth[:3, :3].T + truth[:3, 3]
        d435_pixels, d435_valid = d435.project(points_d435)
        lumos_pixels, lumos_valid = lumos.project(points_lumos)
        assert d435_valid.all() and lumos_valid.all()
        d435_pixels += rng.normal(0.0, 0.05, d435_pixels.shape)
        lumos_pixels += rng.normal(0.0, 0.15, lumos_pixels.shape)
        if index % 4 == 0:
            lumos_pixels[index, :] += [5.0, -4.0]
        observations.append(
            DualCameraFitObservation(
                point_ids=tuple(range(len(objects))),
                object_points_m=objects,
                d435_image_points_px=d435_pixels,
                lumos_image_points_px=lumos_pixels,
                t_d435_from_board=board_pose,
                d435_reprojection_rmse_px=0.2,
                old_candidate_lumos_p95_px=8.0,
            )
        )
    manifest: dict[str, object] = {
        "schema_version": 1,
        "purpose": "fit",
        "seed_candidate_id": candidate.candidate_id,
        "target": {"family": "charuco"},
        "motion_or_robot_access": False,
        "observations": [_record(item, index) for index, item in enumerate(observations)],
    }
    seed_payload: dict[str, object] = {
        "schema_version": 1,
        "status": "candidate_only",
        "executable": False,
        "candidate_id": candidate.candidate_id,
        "seed_hypothesis": "d435_extra_inversion_corrected",
        "T_lumos_from_d435": seed.tolist(),
        "d435": {
            "model": "pinhole",
            "distortion_model": "none",
            "width": d435.width,
            "height": d435.height,
            "fx": d435.fx,
            "fy": d435.fy,
            "cx": d435.cx,
            "cy": d435.cy,
        },
        "lumos": {
            "model": "eucm",
            "width": lumos.width,
            "height": lumos.height,
            "fx": lumos.fx,
            "fy": lumos.fy,
            "cx": lumos.cx,
            "cy": lumos.cy,
            "alpha": lumos.alpha,
            "beta": lumos.beta,
        },
    }
    return manifest, candidate, truth, seed_payload


def test_recovers_known_transform_with_noise_and_outliers() -> None:
    manifest, seed, truth, _seed_payload = _synthetic_problem()

    result = solve_dual_camera_refit(manifest, seed)

    translation_error = np.linalg.norm(result.transform[:3, 3] - truth[:3, 3])
    rotation_error_deg = np.degrees(
        Rotation.from_matrix(result.transform[:3, :3].T @ truth[:3, :3]).magnitude()
    )
    assert translation_error <= 0.001
    assert rotation_error_deg <= 0.2
    assert result.p95_px <= 2.0
    assert result.samples == 12
    assert result.corners == 12 * 70


def test_writes_non_executable_content_addressed_candidate(tmp_path: Path) -> None:
    manifest, seed, _truth, seed_payload = _synthetic_problem()
    result = solve_dual_camera_refit(manifest, seed)
    path = tmp_path / "generated.json"

    write_refit_candidate(
        path,
        result=result,
        seed_payload=seed_payload,
        fit_dataset_id="sha256:" + "b" * 64,
    )

    stored = json.loads(path.read_text(encoding="utf-8"))
    loaded = load_dual_camera_candidate(path)
    assert stored["executable"] is False
    assert stored["status"] == "candidate_only"
    assert loaded.candidate_id == stored["candidate_id"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda payload: payload.update(purpose="validation"), "purpose"),
        (lambda payload: payload["observations"].pop(), "12"),
    ],
)
def test_rejects_wrong_purpose_or_insufficient_samples(change, message: str) -> None:
    manifest, seed, _truth, _seed_payload = _synthetic_problem()
    change(manifest)

    with pytest.raises(CalibrationCaptureError, match=message):
        solve_dual_camera_refit(manifest, seed)
