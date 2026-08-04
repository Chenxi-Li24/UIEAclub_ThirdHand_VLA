from __future__ import annotations

import numpy as np
import pytest

from vision.camera_models import PinholeCamera, SeucmCamera
from vision.depth_registration import (
    rasterize_lumos_points,
    register_depth_to_lumos,
    select_masked_cloud,
)
from vision.types import InvalidDataError


def tiny_d435() -> PinholeCamera:
    return PinholeCamera(2.0, 2.0, 1.0, 1.0, 3, 3)


def tiny_lumos() -> SeucmCamera:
    return SeucmCamera(2.0, 2.0, 1.0, 1.0, 0.5, 1.0, 3, 3)


def test_z_buffer_keeps_nearest_lumos_surface_and_counts_sources():
    result = rasterize_lumos_points(
        uv_px=np.array([[5.2, 7.1], [5.4, 7.4], [8.0, 2.0]]),
        points_lumos_m=np.array(
            [[0.0, 0.0, 0.8], [0.0, 0.0, 1.2], [0.1, 0.1, 0.5]]
        ),
        image_shape=(12, 12),
    )
    assert result.valid[7, 5]
    assert result.z_m[7, 5] == pytest.approx(0.8)
    assert result.range_m[7, 5] == pytest.approx(0.8)
    assert result.source_count[7, 5] == 2
    np.testing.assert_allclose(result.points_lumos_m[7, 5], [0.0, 0.0, 0.8])


def test_rasterization_ignores_out_of_frame_behind_and_nonfinite_points():
    result = rasterize_lumos_points(
        uv_px=np.array([[-1.0, 1.0], [1.0, 1.0], [1.0, np.nan], [2.0, 2.0]]),
        points_lumos_m=np.array(
            [[0.0, 0.0, 1.0], [0.0, 0.0, -0.1], [0.0, 0.0, 0.5], [0.2, 0.2, 0.6]]
        ),
        image_shape=(3, 3),
    )
    assert result.valid.sum() == 1
    assert result.valid[2, 2]


def test_center_depth_registers_under_identity_transform():
    depth = np.zeros((3, 3), dtype=float)
    depth[1, 1] = 1.0
    result = register_depth_to_lumos(
        depth,
        tiny_d435(),
        np.eye(4),
        tiny_lumos(),
        min_depth_m=0.1,
        max_depth_m=3.0,
    )
    assert result.valid.sum() == 1
    assert result.valid[1, 1]
    np.testing.assert_allclose(result.points_lumos_m[1, 1], [0.0, 0.0, 1.0])


def test_registration_applies_d435_to_lumos_translation():
    depth = np.zeros((3, 3), dtype=float)
    depth[1, 1] = 1.0
    transform = np.eye(4)
    transform[0, 3] = 0.25
    result = register_depth_to_lumos(
        depth,
        tiny_d435(),
        transform,
        tiny_lumos(),
        min_depth_m=0.1,
        max_depth_m=3.0,
    )
    assert result.valid.sum() == 1
    row, col = np.argwhere(result.valid)[0]
    np.testing.assert_allclose(result.points_lumos_m[row, col], [0.25, 0.0, 1.0])


def test_registration_rejects_zero_nan_and_out_of_range_depth():
    depth = np.array(
        [
            [0.0, np.nan, 0.0],
            [0.05, 0.5, 12.0],
            [0.0, 0.0, 0.0],
        ]
    )
    result = register_depth_to_lumos(
        depth,
        tiny_d435(),
        np.eye(4),
        tiny_lumos(),
        min_depth_m=0.1,
        max_depth_m=3.0,
    )
    assert result.valid.sum() == 1
    assert result.z_m[result.valid][0] == pytest.approx(0.5)


def test_mask_selection_returns_only_registered_3d_points():
    result = rasterize_lumos_points(
        np.array([[0.0, 0.0], [1.0, 1.0]]),
        np.array([[0.0, 0.0, 0.5], [0.1, 0.1, 0.7]]),
        (2, 2),
    )
    mask = np.array([[False, False], [False, True]])
    cloud = select_masked_cloud(result, mask)
    np.testing.assert_allclose(cloud, [[0.1, 0.1, 0.7]])


def test_registration_validates_image_shape_range_and_mask():
    with pytest.raises(InvalidDataError):
        register_depth_to_lumos(
            np.ones((2, 2)), tiny_d435(), np.eye(4), tiny_lumos(), 0.1, 3.0
        )
    with pytest.raises(InvalidDataError):
        register_depth_to_lumos(
            np.ones((3, 3)), tiny_d435(), np.eye(4), tiny_lumos(), 3.0, 0.1
        )
    result = rasterize_lumos_points(
        np.array([[0.0, 0.0]]), np.array([[0.0, 0.0, 0.5]]), (2, 2)
    )
    with pytest.raises(InvalidDataError):
        select_masked_cloud(result, np.ones((3, 3), dtype=bool))

