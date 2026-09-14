from __future__ import annotations

import numpy as np
import pytest

from thirdhand_vision.core.camera import PinholeCamera, SeucmCamera
from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.core.transforms import (
    invert_transform,
    make_transform,
    transform_points,
    validate_transform,
)


def test_pinhole_projection_round_trips_axial_depth() -> None:
    camera = PinholeCamera(fx=100.0, fy=120.0, cx=10.0, cy=8.0, width=32, height=24)
    pixels = np.array([[10.0, 8.0], [20.0, 14.0]])
    points = camera.deproject_z(pixels, np.array([1.0, 2.0]))
    projected, valid = camera.project(points)
    assert valid.tolist() == [True, True]
    np.testing.assert_allclose(projected, pixels)


def test_seucm_projection_round_trips_valid_rays() -> None:
    camera = SeucmCamera(
        fx=180.0,
        fy=180.0,
        cx=160.0,
        cy=160.0,
        alpha=0.55,
        beta=1.1,
        width=320,
        height=320,
    )
    pixels = np.array([[160.0, 160.0], [100.0, 120.0], [210.0, 180.0]])
    rays, unprojected = camera.unproject(pixels)
    reprojection, projected = camera.project(rays * 2.0)
    assert unprojected.tolist() == [True, True, True]
    assert projected.tolist() == [True, True, True]
    np.testing.assert_allclose(reprojection, pixels, atol=1e-9)


def test_transform_round_trip_preserves_points() -> None:
    rotation = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    transform = make_transform(rotation, np.array([0.1, -0.2, 0.3]))
    points = np.array([[0.4, 0.2, 1.0], [0.0, 0.0, 0.5]])
    restored = transform_points(invert_transform(transform), transform_points(transform, points))
    np.testing.assert_allclose(restored, points, atol=1e-12)


def test_validate_transform_rejects_reflection() -> None:
    reflected = np.eye(4)
    reflected[0, 0] = -1.0
    with pytest.raises(InputValidationError, match="proper rotation"):
        validate_transform(reflected)

