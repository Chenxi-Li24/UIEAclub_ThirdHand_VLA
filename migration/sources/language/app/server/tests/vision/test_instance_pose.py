from __future__ import annotations

import numpy as np
import pytest

from vision.depth_registration import RegisteredDepth
from vision.instance_pose import InstancePoseConfig, estimate_instance_pose
from vision.types import FrameStamp, InvalidDataError


def registered(points, valid=None):
    point_image = np.asarray(points, dtype=float)
    height, width, _ = point_image.shape
    valid_image = (
        np.isfinite(point_image).all(axis=2)
        if valid is None
        else np.asarray(valid, dtype=bool)
    )
    z_image = np.full((height, width), np.nan)
    range_image = np.full((height, width), np.nan)
    z_image[valid_image] = point_image[..., 2][valid_image]
    range_image[valid_image] = np.linalg.norm(point_image[valid_image], axis=1)
    frozen_points = np.full_like(point_image, np.nan)
    frozen_points[valid_image] = point_image[valid_image]
    return RegisteredDepth(
        z_m=z_image,
        range_m=range_image,
        valid=valid_image,
        source_count=valid_image.astype(np.int32),
        points_lumos_m=frozen_points,
    )


def translated_identity(xyz):
    transform = np.eye(4)
    transform[:3, 3] = np.asarray(xyz, dtype=float)
    return transform


def stamp(timestamp_ns=10):
    return FrameStamp("lumos+d435", 1, timestamp_ns)


def config(**overrides):
    values = {
        "min_points": 4,
        "erosion_px": 1,
        "mad_scale": 3.5,
        "noise_floor_m": 0.002,
    }
    values.update(overrides)
    return InstancePoseConfig(**values)


def test_pose_uses_eroded_mask_and_rejects_background_boundary():
    points = np.empty((5, 5, 3), dtype=float)
    points[:] = [0.8, 0.8, 1.2]
    inner_xy = [-0.01, 0.0, 0.01]
    for row, y in enumerate(inner_xy, start=1):
        for column, x in enumerate(inner_xy, start=1):
            points[row, column] = [x, y, 0.5]

    pose = estimate_instance_pose(
        registered(points),
        mask=np.ones((5, 5), dtype=bool),
        t_base_from_lumos=translated_identity([0.1, 0.0, 0.0]),
        stamp=stamp(),
        calibration_id="sha256:pose-test",
        config=config(),
    )

    np.testing.assert_allclose(pose.xyz_m, [0.1, 0.0, 0.5], atol=1e-12)
    assert pose.frame == "robot_base"
    assert pose.calibration_id == "sha256:pose-test"


def test_mad_filter_rejects_distant_point_inside_mask():
    points = np.zeros((3, 3, 3), dtype=float)
    points[..., 2] = 0.5
    points[0, 0] = [2.0, -3.0, 4.0]

    pose = estimate_instance_pose(
        registered(points),
        mask=np.ones((3, 3), dtype=bool),
        t_base_from_lumos=np.eye(4),
        stamp=stamp(),
        calibration_id="sha256:pose-test",
        config=config(erosion_px=0),
    )

    np.testing.assert_allclose(pose.xyz_m, [0.0, 0.0, 0.5], atol=1e-12)


def test_covariance_is_finite_symmetric_positive_semidefinite_with_noise_floor():
    points = np.array(
        [
            [[-0.01, -0.01, 0.49], [0.01, -0.01, 0.50]],
            [[-0.01, 0.01, 0.50], [0.01, 0.01, 0.51]],
        ]
    )
    pose = estimate_instance_pose(
        registered(points),
        mask=np.ones((2, 2), dtype=bool),
        t_base_from_lumos=np.eye(4),
        stamp=stamp(),
        calibration_id="sha256:pose-test",
        config=config(erosion_px=0),
    )
    assert np.isfinite(pose.covariance_m2).all()
    np.testing.assert_allclose(pose.covariance_m2, pose.covariance_m2.T, atol=1e-15)
    assert np.min(np.linalg.eigvalsh(pose.covariance_m2)) >= 0.002**2 - 1e-15


def test_covariance_conservatively_keeps_inlier_spread_for_median_center():
    points = np.array(
        [
            [[-0.01, 0.0, 0.5], [0.01, 0.0, 0.5]],
            [[-0.01, 0.0, 0.5], [0.01, 0.0, 0.5]],
        ]
    )
    result = estimate_instance_pose(
        registered(points),
        mask=np.ones((2, 2), dtype=bool),
        t_base_from_lumos=np.eye(4),
        stamp=stamp(),
        calibration_id="sha256:pose-test",
        config=config(erosion_px=0),
    )
    sample_variance_x = np.var(points[..., 0], ddof=1)
    assert result.covariance_m2[0, 0] >= sample_variance_x


def test_sparse_or_fully_eroded_mask_is_rejected():
    points = np.zeros((3, 3, 3), dtype=float)
    points[..., 2] = 0.5
    one_pixel = np.zeros((3, 3), dtype=bool)
    one_pixel[1, 1] = True
    with pytest.raises(InvalidDataError, match="insufficient valid depth points"):
        estimate_instance_pose(
            registered(points),
            one_pixel,
            np.eye(4),
            stamp(),
            "sha256:pose-test",
            config=config(erosion_px=0),
        )
    with pytest.raises(InvalidDataError, match="insufficient valid depth points"):
        estimate_instance_pose(
            registered(points),
            np.ones((3, 3), dtype=bool),
            np.eye(4),
            stamp(),
            "sha256:pose-test",
            config=config(erosion_px=2),
        )


def test_mask_shape_dtype_transform_and_calibration_are_validated():
    points = np.zeros((2, 2, 3), dtype=float)
    points[..., 2] = 0.5
    depth = registered(points)
    with pytest.raises(InvalidDataError, match="boolean array"):
        estimate_instance_pose(
            depth,
            np.ones((2, 2), dtype=np.uint8),
            np.eye(4),
            stamp(),
            "sha256:pose-test",
            config=config(erosion_px=0),
        )
    with pytest.raises(InvalidDataError, match="matching registered depth"):
        estimate_instance_pose(
            depth,
            np.ones((3, 3), dtype=bool),
            np.eye(4),
            stamp(),
            "sha256:pose-test",
            config=config(erosion_px=0),
        )
    bad_transform = np.eye(4)
    bad_transform[3, 3] = 2.0
    with pytest.raises(InvalidDataError):
        estimate_instance_pose(
            depth,
            np.ones((2, 2), dtype=bool),
            bad_transform,
            stamp(),
            "sha256:pose-test",
            config=config(erosion_px=0),
        )
    with pytest.raises(InvalidDataError, match="calibration_id"):
        estimate_instance_pose(
            depth,
            np.ones((2, 2), dtype=bool),
            np.eye(4),
            stamp(),
            "unversioned",
            config=config(erosion_px=0),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"min_points": 0},
        {"erosion_px": -1},
        {"mad_scale": 0.0},
        {"noise_floor_m": 0.0},
        {"mad_scale": np.inf},
    ],
)
def test_pose_config_rejects_unsafe_values(overrides):
    with pytest.raises(InvalidDataError):
        config(**overrides)
