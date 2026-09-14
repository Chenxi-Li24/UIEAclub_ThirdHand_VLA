from __future__ import annotations

import numpy as np
import pytest

from vision.active_view_geometry import contains_estimate, estimate_table_target
from vision.active_view_types import CoarseTargetEstimate, TablePlane
from vision.camera_models import SeucmCamera
from vision.types import FrameStamp, InvalidDataError


CALIBRATION_ID = "sha256:" + "c" * 64


def camera() -> SeucmCamera:
    return SeucmCamera(
        fx=8.0,
        fy=8.0,
        cx=4.0,
        cy=4.0,
        alpha=0.5,
        beta=1.0,
        width=9,
        height=9,
    )


def camera_above_table() -> np.ndarray:
    transform = np.eye(4)
    transform[:3, :3] = np.diag([1.0, -1.0, -1.0])
    transform[:3, 3] = [0.0, 0.0, 1.0]
    return transform


def horizontal_camera() -> np.ndarray:
    transform = np.eye(4)
    transform[:3, :3] = np.array(
        [
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ]
    )
    transform[:3, 3] = [0.0, 0.0, 1.0]
    return transform


def table(*, validated: bool = True) -> TablePlane:
    return TablePlane(
        normal_base=np.array([0.0, 0.0, 1.0]),
        offset_m=0.0,
        position_rmse_m=0.004,
        calibration_id=CALIBRATION_ID,
        validated=validated,
    )


def stamp() -> FrameStamp:
    return FrameStamp("lumos_rgb", 4, 1_000)


def test_mask_lower_boundary_estimates_table_location_not_mask_center() -> None:
    mask = np.zeros((9, 9), dtype=bool)
    mask[2:8, 3:6] = True

    estimate = estimate_table_target(
        7,
        mask,
        camera(),
        camera_above_table(),
        table(),
        stamp(),
    )

    expected_rays, valid = camera().unproject(np.array([[3, 7], [4, 7], [5, 7]]))
    assert valid.all()
    rotation = camera_above_table()[:3, :3]
    expected_rays_base = expected_rays @ rotation.T
    distance = -1.0 / expected_rays_base[:, 2]
    expected_xy = expected_rays_base[:, :2] * distance[:, None]

    assert estimate.identity_id == 7
    np.testing.assert_allclose(estimate.samples_xy_m, expected_xy)
    np.testing.assert_allclose(
        estimate.center_xy_m,
        np.median(estimate.samples_xy_m, axis=0),
    )
    assert estimate.covariance_xy_m2.shape == (2, 2)
    assert np.min(np.linalg.eigvalsh(estimate.covariance_xy_m2)) >= table().position_rmse_m**2
    assert estimate.calibration_id == CALIBRATION_ID


def test_parallel_table_rays_fail_closed() -> None:
    mask = np.zeros((9, 9), dtype=bool)
    mask[4, 3:6] = True

    with pytest.raises(InvalidDataError, match="table intersection"):
        estimate_table_target(
            1,
            mask,
            camera(),
            horizontal_camera(),
            table(),
            stamp(),
        )


@pytest.mark.parametrize(
    "mask",
    [
        np.zeros((9, 9), dtype=bool),
        np.ones((9, 9), dtype=np.uint8),
        np.ones((8, 9), dtype=bool),
    ],
)
def test_invalid_instance_masks_are_rejected(mask: np.ndarray) -> None:
    with pytest.raises(InvalidDataError, match="mask"):
        estimate_table_target(
            1,
            mask,
            camera(),
            camera_above_table(),
            table(),
            stamp(),
        )


def test_unvalidated_table_is_not_observation_evidence() -> None:
    mask = np.zeros((9, 9), dtype=bool)
    mask[2:8, 3:6] = True

    with pytest.raises(InvalidDataError, match="validated table"):
        estimate_table_target(
            1,
            mask,
            camera(),
            camera_above_table(),
            table(validated=False),
            stamp(),
        )


def test_convex_coverage_includes_boundary_but_honors_required_margin() -> None:
    estimate = CoarseTargetEstimate(
        identity_id=2,
        center_xy_m=np.array([0.5, 0.5]),
        covariance_xy_m2=np.eye(2) * 0.001,
        samples_xy_m=np.array([[0.0, 0.5], [0.5, 0.4], [0.5, 0.6]]),
        source_stamp=stamp(),
        calibration_id=CALIBRATION_ID,
    )
    polygon_ccw = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])

    assert contains_estimate(polygon_ccw, estimate, 0.0) is True
    assert contains_estimate(polygon_ccw, estimate, 0.01) is False
    assert contains_estimate(polygon_ccw[::-1], estimate, 0.0) is True


def test_non_convex_coverage_is_rejected() -> None:
    estimate = CoarseTargetEstimate(
        identity_id=2,
        center_xy_m=np.array([0.5, 0.5]),
        covariance_xy_m2=np.eye(2) * 0.001,
        samples_xy_m=np.array([[0.4, 0.5], [0.5, 0.4], [0.6, 0.5]]),
        source_stamp=stamp(),
        calibration_id=CALIBRATION_ID,
    )
    non_convex = np.array([[0.0, 0.0], [1.0, 0.0], [0.2, 0.2], [0.0, 1.0]])

    with pytest.raises(InvalidDataError, match="convex"):
        contains_estimate(non_convex, estimate, 0.0)


def test_active_view_geometry_is_exposed_as_a_public_pure_function() -> None:
    import vision

    assert "estimate_table_target" in vision.__all__
    assert "contains_estimate" in vision.__all__
    assert vision.estimate_table_target is estimate_table_target
