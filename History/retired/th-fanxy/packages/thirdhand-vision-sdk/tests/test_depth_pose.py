from __future__ import annotations

import numpy as np
import pytest

from thirdhand_vision.core.camera import PinholeCamera, SeucmCamera
from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.core.types import FrameStamp
from thirdhand_vision.geometry.depth import (
    RegisteredDepth,
    rasterize_lumos_points,
    register_depth,
)
from thirdhand_vision.geometry.pose import InstancePoseConfig, estimate_instance_pose


def test_rasterization_keeps_nearest_lumos_point() -> None:
    result = rasterize_lumos_points(
        uv_px=np.array([[3.0, 2.0], [3.0, 2.0]]),
        points_lumos_m=np.array([[0.0, 0.0, 0.8], [0.0, 0.0, 0.4]]),
        image_shape=(5, 6),
    )
    assert result.z_m[2, 3] == pytest.approx(0.4)
    assert result.source_count[2, 3] == 2
    np.testing.assert_allclose(result.points_lumos_m[2, 3], [0.0, 0.0, 0.4])


def test_register_depth_projects_d435_center_to_lumos_center() -> None:
    d435 = PinholeCamera(fx=100.0, fy=100.0, cx=1.0, cy=1.0, width=3, height=3)
    lumos = SeucmCamera(
        fx=100.0,
        fy=100.0,
        cx=2.0,
        cy=2.0,
        alpha=0.5,
        beta=1.0,
        width=5,
        height=5,
    )
    depth = np.full((3, 3), np.nan, dtype=np.float32)
    depth[1, 1] = 0.6
    result = register_depth(
        depth,
        d435=d435,
        t_lumos_from_d435=np.eye(4),
        lumos=lumos,
        min_depth_m=0.1,
        max_depth_m=2.0,
    )
    assert result.valid[2, 2]
    assert result.z_m[2, 2] == pytest.approx(0.6)


def test_pose_uses_median_and_rejects_single_outlier() -> None:
    height = width = 9
    points = np.full((height, width, 3), np.nan)
    valid = np.zeros((height, width), dtype=bool)
    cloud = []
    for row in range(2, 7):
        for col in range(2, 7):
            point = np.array([0.10 + col * 0.001, 0.20 + row * 0.001, 0.50])
            points[row, col] = point
            valid[row, col] = True
            cloud.append(point)
    points[4, 4] = [9.0, 9.0, 9.0]
    registered = RegisteredDepth(
        z_m=points[..., 2],
        range_m=np.linalg.norm(points, axis=2),
        valid=valid,
        source_count=valid.astype(np.int32),
        points_lumos_m=points,
    )
    pose = estimate_instance_pose(
        registered=registered,
        mask=np.ones((height, width), dtype=bool),
        t_output_from_lumos=np.eye(4),
        stamp=FrameStamp(source="fusion", frame_id=1, monotonic_ns=100),
        calibration_id="sha256:test",
        config=InstancePoseConfig(
            min_points=8,
            erosion_px=1,
            mad_scale=3.5,
            noise_floor_m=0.002,
        ),
    )
    np.testing.assert_allclose(pose.xyz_m, [0.104, 0.204, 0.5], atol=0.002)
    assert np.all(np.diag(pose.covariance_m2) >= 0.002**2)


def test_pose_refuses_too_few_valid_mask_points() -> None:
    registered = RegisteredDepth.empty((4, 4))
    with pytest.raises(InputValidationError, match="insufficient valid depth points"):
        estimate_instance_pose(
            registered=registered,
            mask=np.ones((4, 4), dtype=bool),
            t_output_from_lumos=np.eye(4),
            stamp=FrameStamp(source="fusion", frame_id=1, monotonic_ns=1),
            calibration_id="sha256:test",
            config=InstancePoseConfig(3, 0, 3.5, 0.002),
        )
