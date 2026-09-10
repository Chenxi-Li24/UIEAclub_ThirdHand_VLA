from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.geometry import make_transform, rpy_xyz_to_matrix
from vision_models.calibration_targets import TargetCorners
from vision_models.legacy_dual_camera_validation import (
    evaluate_legacy_candidate_pair,
    pose_is_distinct,
    summarize_legacy_candidate,
)


def _synthetic_pair(candidate_offset_m: float = 0.0, board_offset_x_m: float = 0.0):
    d435 = PinholeCamera(606.0, 606.0, 329.0, 243.0, 640, 480)
    lumos = SeucmCamera(392.0, 392.0, 637.0, 641.0, 0.68, 0.75, 1280, 1280)
    object_points = np.column_stack(
        (
            np.linspace(-0.09, 0.09, 32),
            np.tile([-0.06, -0.02, 0.02, 0.06], 8),
            np.zeros(32),
        )
    )
    t_d435_from_board = make_transform(
        rpy_xyz_to_matrix([0.08, -0.12, 0.04]),
        [0.01 + board_offset_x_m, -0.02, 0.65],
    )
    true_relative = make_transform(
        rpy_xyz_to_matrix([0.01, 0.08, -0.02]),
        [-0.10, 0.0, -0.10],
    )
    d435_points = (
        object_points @ t_d435_from_board[:3, :3].T
        + t_d435_from_board[:3, 3]
    )
    lumos_points = d435_points @ true_relative[:3, :3].T + true_relative[:3, 3]
    d435_pixels, d435_valid = d435.project(d435_points)
    lumos_pixels, lumos_valid = lumos.project(lumos_points)
    assert d435_valid.all() and lumos_valid.all()
    point_ids = tuple(range(32))
    d435_detection = TargetCorners(point_ids, object_points, d435_pixels)
    lumos_detection = TargetCorners(point_ids, object_points, lumos_pixels)
    candidate = np.array(true_relative, copy=True)
    candidate[0, 3] += candidate_offset_m
    return d435, lumos, candidate, d435_detection, lumos_detection


def test_candidate_pair_uses_d435_pnp_then_native_seucm_reprojection() -> None:
    d435, lumos, candidate, d435_detection, lumos_detection = _synthetic_pair()

    result = evaluate_legacy_candidate_pair(
        d435=d435,
        lumos=lumos,
        t_lumos_from_d435=candidate,
        d435_detection=d435_detection,
        lumos_detection=lumos_detection,
    )

    assert result.common_points == 32
    assert result.d435_reprojection_rmse_px < 1e-6
    assert result.lumos_reprojection_p95_px < 1e-5
    assert result.passes_pixel_gate is True


def test_wrong_relative_translation_fails_cross_camera_pixel_gate() -> None:
    d435, lumos, candidate, d435_detection, lumos_detection = _synthetic_pair(0.05)

    result = evaluate_legacy_candidate_pair(
        d435=d435,
        lumos=lumos,
        t_lumos_from_d435=candidate,
        d435_detection=d435_detection,
        lumos_detection=lumos_detection,
    )

    assert result.lumos_reprojection_p95_px > 10.0
    assert result.passes_pixel_gate is False


def test_summary_can_validate_relative_extrinsic_but_never_authorize_execution() -> None:
    d435, lumos, candidate, d435_detection, lumos_detection = _synthetic_pair()
    observations = []
    for index in range(10):
        d435, lumos, candidate, d435_detection, lumos_detection = _synthetic_pair(
            board_offset_x_m=-0.09 + index * 0.02
        )
        observations.append(
            evaluate_legacy_candidate_pair(
                d435=d435,
                lumos=lumos,
                t_lumos_from_d435=candidate,
                d435_detection=d435_detection,
                lumos_detection=lumos_detection,
            )
        )

    summary = summarize_legacy_candidate(
        observations,
        candidate_id="sha256:" + "a" * 64,
    )

    assert summary["relative_extrinsic_validated"] is True
    assert summary["executable"] is False
    assert summary["required_samples"] == 10
    assert summary["distinct_poses"] == 10
    assert summary["lumos_reprojection_p95_px"] < 1e-5
    assert "handeye_validation_missing" in summary["remaining_blockers"]
    assert math.isfinite(summary["d435_reprojection_rmse_px"])


def test_summary_rejects_ten_repeated_observations_of_one_pose() -> None:
    d435, lumos, candidate, d435_detection, lumos_detection = _synthetic_pair()
    observation = evaluate_legacy_candidate_pair(
        d435=d435,
        lumos=lumos,
        t_lumos_from_d435=candidate,
        d435_detection=d435_detection,
        lumos_detection=lumos_detection,
    )

    summary = summarize_legacy_candidate(
        (observation,) * 10,
        candidate_id="sha256:" + "a" * 64,
    )

    assert summary["samples"] == 10
    assert summary["distinct_poses"] == 1
    assert summary["relative_extrinsic_validated"] is False


def test_pose_is_distinct_requires_translation_or_rotation_from_every_pose() -> None:
    d435, lumos, candidate, d435_detection, lumos_detection = _synthetic_pair()
    origin = evaluate_legacy_candidate_pair(
        d435=d435,
        lumos=lumos,
        t_lumos_from_d435=candidate,
        d435_detection=d435_detection,
        lumos_detection=lumos_detection,
    )
    duplicate = replace(
        origin,
        t_d435_from_board=make_transform(
            origin.t_d435_from_board[:3, :3],
            origin.t_d435_from_board[:3, 3] + [0.014, 0.0, 0.0],
        ),
    )
    translated = replace(
        origin,
        t_d435_from_board=make_transform(
            origin.t_d435_from_board[:3, :3],
            origin.t_d435_from_board[:3, 3] + [0.015, 0.0, 0.0],
        ),
    )
    rotated = replace(
        origin,
        t_d435_from_board=make_transform(
            origin.t_d435_from_board[:3, :3]
            @ rpy_xyz_to_matrix([0.0, 0.0, math.radians(3.0)]),
            origin.t_d435_from_board[:3, 3],
        ),
    )

    assert pose_is_distinct(duplicate, (origin,)) is False
    assert pose_is_distinct(translated, (origin,)) is True
    assert pose_is_distinct(rotated, (origin,)) is True
    assert pose_is_distinct(origin, ()) is True


def test_summary_rejects_one_pose_that_fails_its_pixel_gate() -> None:
    observations = []
    for index in range(10):
        d435, lumos, candidate, d435_detection, lumos_detection = _synthetic_pair(
            board_offset_x_m=-0.09 + index * 0.02
        )
        observations.append(
            evaluate_legacy_candidate_pair(
                d435=d435,
                lumos=lumos,
                t_lumos_from_d435=candidate,
                d435_detection=d435_detection,
                lumos_detection=lumos_detection,
            )
        )
    bad_errors = np.zeros(32)
    bad_errors[-2:] = 50.0
    observations[-1] = replace(
        observations[-1],
        lumos_reprojection_p95_px=50.0,
        passes_pixel_gate=False,
        lumos_errors_px=bad_errors,
    )

    summary = summarize_legacy_candidate(
        observations,
        candidate_id="sha256:" + "a" * 64,
    )

    assert summary["lumos_reprojection_p95_px"] < 4.0
    assert summary["relative_extrinsic_validated"] is False
