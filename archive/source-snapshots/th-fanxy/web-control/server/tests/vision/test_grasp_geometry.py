from __future__ import annotations

import json

import numpy as np
import pytest
import vision
from vision.active_view_types import TablePlane
from vision.camera_models import PinholeCamera
from vision.depth_registration import RegisteredDepth
from vision.grasp_geometry import (
    GraspGeometryConfig,
    GraspPreviewAccumulator,
    evaluate_top_down_grasp,
)
from vision.types import FrameStamp

CALIBRATION_ID = "sha256:" + "a" * 64
EVIDENCE_IDS = ("sha256:" + "b" * 64, "sha256:" + "c" * 64)


def config(**changes) -> GraspGeometryConfig:
    values = {
        "min_points": 80,
        "erosion_px": 0,
        "mad_scale": 4.0,
        "noise_floor_m": 0.001,
        "inner_roi_fraction": 0.60,
        "min_central_fraction": 0.80,
        "max_axis_mad_m": 0.005,
        "min_object_height_m": 0.010,
        "max_object_height_m": 0.250,
        "min_gripper_width_m": 0.010,
        "max_gripper_width_m": 0.085,
        "grasp_width_margin_m": 0.006,
        "pregrasp_clearance_m": 0.080,
        "retreat_clearance_m": 0.100,
        "workspace_min_m": np.array([0.10, -0.40, 0.01]),
        "workspace_max_m": np.array([0.70, 0.40, 0.45]),
        "stable_sample_count": 5,
        "max_center_deviation_m": 0.010,
        "max_temporal_axis_mad_m": 0.005,
    }
    values.update(changes)
    return GraspGeometryConfig(**values)


def table() -> TablePlane:
    return TablePlane(
        normal_base=[0.0, 0.0, 1.0],
        offset_m=0.0,
        position_rmse_m=0.003,
        calibration_id=CALIBRATION_ID,
        validated=True,
    )


def registered_cloud(
    *,
    angle_rad: float = 0.45,
    planar_length_m: float = 0.060,
    planar_width_m: float = 0.030,
    base_z_m: float = 0.060,
    center_d435_x_m: float = 0.0,
) -> tuple[RegisteredDepth, np.ndarray]:
    height = width = 100
    valid = np.zeros((height, width), dtype=bool)
    mask = np.zeros((height, width), dtype=bool)
    points = np.full((height, width, 3), np.nan, dtype=float)
    rows, cols = np.mgrid[40:60, 40:60]
    local_x = np.linspace(-planar_length_m / 2, planar_length_m / 2, cols.size)
    local_y = np.tile(np.linspace(-planar_width_m / 2, planar_width_m / 2, 20), 20)
    cosine, sine = np.cos(angle_rad), np.sin(angle_rad)
    x = cosine * local_x - sine * local_y + center_d435_x_m
    y = sine * local_x + cosine * local_y
    z = np.linspace(0.46, 0.48, cols.size)
    points[rows.ravel(), cols.ravel()] = np.column_stack((x, y, z))
    valid[rows, cols] = True
    mask[38:62, 38:62] = True
    z_image = np.full((height, width), np.nan)
    range_image = np.full((height, width), np.nan)
    z_image[valid] = points[valid, 2]
    range_image[valid] = np.linalg.norm(points[valid], axis=1)
    counts = np.zeros((height, width), dtype=np.int32)
    counts[valid] = 1
    registered = RegisteredDepth(z_image, range_image, valid, counts, points)
    t_base_from_lumos = np.eye(4)
    t_base_from_lumos[:3, 3] = [0.40, 0.0, base_z_m - 0.47]
    return registered, mask, t_base_from_lumos


def evaluate(**changes):
    registered, mask, t_base_from_lumos = registered_cloud(
        **changes.pop("cloud", {})
    )
    return evaluate_top_down_grasp(
        identity_id=7,
        detection_id=3,
        registered=registered,
        target_mask=mask,
        d435=PinholeCamera(100.0, 100.0, 50.0, 50.0, 100, 100),
        t_d435_from_lumos=np.eye(4),
        t_base_from_lumos=t_base_from_lumos,
        table=changes.pop("table", table()),
        source_stamp=changes.pop("source_stamp", FrameStamp("lumos_rgb+d435_depth", 9, 100)),
        calibration_id=changes.pop("calibration_id", CALIBRATION_ID),
        evidence_ids=changes.pop("evidence_ids", EVIDENCE_IDS),
        config=changes.pop("config", config()),
        d435_instance_mask=changes.pop("d435_instance_mask", None),
    )


def test_masked_cloud_produces_deterministic_pca_grasp_geometry():
    assert vision.evaluate_top_down_grasp is evaluate_top_down_grasp
    first = evaluate()
    second = evaluate()

    assert first.blockers == ()
    assert first.candidate is not None
    assert first.candidate.identity_id == 7
    assert first.candidate.valid_points == 400
    assert first.candidate.central_fraction == pytest.approx(1.0)
    assert first.candidate.width_m < 0.085
    assert first.candidate.object_height_m > 0.05
    assert first.candidate.grasp_lumos_px == second.candidate.grasp_lumos_px
    np.testing.assert_allclose(first.candidate.grasp_xyz_m, second.candidate.grasp_xyz_m)
    assert first.candidate.yaw_rad == pytest.approx(second.candidate.yaw_rad)
    assert -np.pi / 2 <= first.candidate.yaw_rad < np.pi / 2
    assert first.candidate.grasp_xyz_m.flags.writeable is False
    assert first.candidate.pregrasp_xyz_m[2] > first.candidate.grasp_xyz_m[2]


def test_grasp_geometry_excludes_depth_outside_verified_d435_mask():
    d435_mask = np.zeros((100, 100), dtype=bool)
    d435_mask[:, :50] = True

    result = evaluate(d435_instance_mask=d435_mask)

    assert result.candidate is not None
    assert 80 <= result.candidate.valid_points < 400

    unrelated = np.zeros((100, 100), dtype=bool)
    unrelated[0, 0] = True
    blocked = evaluate(d435_instance_mask=unrelated)
    assert blocked.candidate is None
    assert blocked.blockers == ("insufficient_depth_points",)


@pytest.mark.parametrize(
    "cloud_changes,config_changes,expected",
    [
        ({}, {"min_points": 500}, "insufficient_depth_points"),
        ({"center_d435_x_m": 0.18}, {}, "insufficient_central_coverage"),
        (
            {"planar_length_m": 0.20, "planar_width_m": 0.20},
            {},
            "grasp_width_out_of_range",
        ),
        ({"base_z_m": 0.004}, {}, "object_too_close_to_table"),
        ({"base_z_m": 0.40}, {}, "outside_workspace"),
    ],
)
def test_geometry_gates_fail_closed(cloud_changes, config_changes, expected):
    result = evaluate(cloud=cloud_changes, config=config(**config_changes))
    assert expected in result.blockers
    assert result.allowed is False


def test_five_identity_and_evidence_bound_samples_are_required_for_preview():
    accumulator = GraspPreviewAccumulator(config())
    statuses = []
    for frame_id in range(1, 6):
        evaluation = evaluate(
            source_stamp=FrameStamp("lumos_rgb+d435_depth", frame_id, frame_id * 100)
        )
        statuses.append(accumulator.update(evaluation))

    assert [item.stable_samples for item in statuses] == [1, 2, 3, 4, 5]
    assert all(not item.allowed for item in statuses[:4])
    assert statuses[-1].allowed is True
    assert statuses[-1].blockers == ()
    assert statuses[-1].preview_id.startswith("sha256:")
    payload = statuses[-1].to_dict()
    assert payload["identity_id"] == 7
    assert payload["grasp_xyz_m"] is not None
    encoded = json.dumps(payload, sort_keys=True).lower()
    for forbidden in ("move_l", "move_joint", "set_gripper", "websocket", "can_frame"):
        assert forbidden not in encoded

    changed_identity = evaluate()
    changed_identity = changed_identity.with_identity(8)
    reset = accumulator.update(changed_identity)
    assert reset.stable_samples == 1
    assert "depth_not_stable" in reset.blockers


def test_temporally_inconsistent_centers_remain_blocked():
    accumulator = GraspPreviewAccumulator(config())
    for frame_id, x_offset in enumerate((0.0, 0.0, 0.0, 0.0, 0.025), start=1):
        status = accumulator.update(
            evaluate(
                cloud={"center_d435_x_m": x_offset},
                source_stamp=FrameStamp("lumos_rgb+d435_depth", frame_id, frame_id * 100),
            )
        )

    assert status.allowed is False
    assert "depth_temporally_unstable" in status.blockers
