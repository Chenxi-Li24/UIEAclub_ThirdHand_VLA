import numpy as np

from thirdhand_va.vision.geometry.pointcloud import (
    erode_mask,
    fit_table_plane,
    robust_mask_points,
)


def test_erode_mask_removes_one_pixel_boundary() -> None:
    mask = np.zeros((7, 7), dtype=bool)
    mask[1:6, 1:6] = True

    eroded = erode_mask(mask, radius=1)

    expected = np.zeros_like(mask)
    expected[2:5, 2:5] = True
    np.testing.assert_array_equal(eroded, expected)


def test_robust_points_drop_invalid_range_and_z_outlier() -> None:
    mask = np.ones((5, 5), dtype=bool)
    xyz = np.zeros((5, 5, 3), dtype=np.float32)
    xyz[..., 2] = 0.45
    xyz[0, 0] = np.nan
    xyz[0, 1, 2] = 2.0
    xyz[0, 2, 2] = 0.9

    points, valid_ratio = robust_mask_points(
        xyz,
        mask,
        min_depth_m=0.2,
        max_depth_m=1.2,
        mad_scale=3.5,
    )

    assert points.shape == (22, 3)
    assert valid_ratio == 22 / 25


def test_deterministic_table_plane_recovers_normal_outside_object_mask() -> None:
    yy, xx = np.indices((40, 50))
    xyz = np.empty((40, 50, 3), dtype=np.float32)
    xyz[..., 0] = (xx - 25) * 0.004
    xyz[..., 1] = 0.06
    xyz[..., 2] = 0.4 + yy * 0.001
    mask = np.zeros((40, 50), dtype=bool)
    mask[8:34, 20:30] = True
    xyz[mask] = np.asarray([0.0, 0.0, 0.45], dtype=np.float32)

    first = fit_table_plane(xyz, mask, distance_m=0.002)
    second = fit_table_plane(xyz, mask, distance_m=0.002)

    np.testing.assert_allclose(first.normal, second.normal)
    assert abs(first.normal[1]) > 0.999
    assert first.inlier_ratio > 0.95


def test_normal_hint_selects_the_table_instead_of_a_larger_background_plane() -> None:
    yy, xx = np.indices((40, 50))
    xyz = np.empty((40, 50, 3), dtype=np.float32)
    background = yy < 30
    xyz[..., 0] = (xx - 25) * 0.004
    xyz[..., 1] = (yy - 15) * 0.004
    xyz[..., 2] = 0.60
    xyz[..., 1][~background] = 0.06
    xyz[..., 2][~background] = 0.40 + (yy[~background] - 30) * 0.005
    mask = np.zeros((40, 50), dtype=bool)

    unconstrained = fit_table_plane(xyz, mask, distance_m=0.002)
    constrained = fit_table_plane(
        xyz,
        mask,
        distance_m=0.002,
        normal_hint=np.asarray([0.0, 1.0, 0.0]),
        max_normal_angle_deg=15.0,
    )

    assert abs(unconstrained.normal[2]) > 0.99
    assert abs(constrained.normal[1]) > 0.99
    assert constrained.inlier_count >= 450
