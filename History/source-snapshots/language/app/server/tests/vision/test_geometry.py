from __future__ import annotations

import numpy as np
import pytest

from vision.geometry import (
    invert_transform,
    make_transform,
    rpy_xyz_to_matrix,
    transform_points,
    validate_transform,
)
from vision.types import InvalidDataError


def rx(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def ry(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rz(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def test_rpy_uses_rz_ry_rx_not_rodrigues_vector():
    rpy = np.deg2rad([20.0, -15.0, 35.0])
    expected = rz(rpy[2]) @ ry(rpy[1]) @ rx(rpy[0])
    np.testing.assert_allclose(rpy_xyz_to_matrix(rpy), expected, atol=1e-12)


def test_single_axis_rpy_matches_each_axis_rotation():
    angle = 0.37
    np.testing.assert_allclose(rpy_xyz_to_matrix([angle, 0, 0]), rx(angle), atol=1e-12)
    np.testing.assert_allclose(rpy_xyz_to_matrix([0, angle, 0]), ry(angle), atol=1e-12)
    np.testing.assert_allclose(rpy_xyz_to_matrix([0, 0, angle]), rz(angle), atol=1e-12)


def test_transform_round_trip_for_batch_and_single_point():
    transform = make_transform(
        rpy_xyz_to_matrix([0.2, -0.1, 0.4]),
        [0.3, -0.2, 0.8],
    )
    points = np.array([[0.0, 0.0, 0.0], [0.2, -0.4, 1.1]])
    recovered = transform_points(
        invert_transform(transform),
        transform_points(transform, points),
    )
    np.testing.assert_allclose(recovered, points, atol=1e-12)
    single = transform_points(transform, np.array([0.0, 0.0, 0.0]))
    np.testing.assert_allclose(single, [0.3, -0.2, 0.8], atol=1e-12)


def test_make_transform_copies_inputs():
    rotation = np.eye(3)
    translation = np.array([1.0, 2.0, 3.0])
    transform = make_transform(rotation, translation)
    rotation[0, 0] = 9.0
    translation[0] = 9.0
    np.testing.assert_allclose(transform, np.array([
        [1.0, 0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0, 2.0],
        [0.0, 0.0, 1.0, 3.0],
        [0.0, 0.0, 0.0, 1.0],
    ]))


@pytest.mark.parametrize(
    "transform",
    [
        np.eye(3),
        np.full((4, 4), np.nan),
        np.diag([1.0, 1.0, -1.0, 1.0]),
        np.array([[2.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]),
        np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 1.0, 1.0]]),
    ],
)
def test_validate_transform_fails_closed(transform):
    with pytest.raises(InvalidDataError):
        validate_transform(transform)


def test_transform_points_rejects_nonfinite_or_bad_shape():
    with pytest.raises(InvalidDataError):
        transform_points(np.eye(4), np.array([1.0, 2.0]))
    with pytest.raises(InvalidDataError):
        transform_points(np.eye(4), np.array([[1.0, np.inf, 2.0]]))
