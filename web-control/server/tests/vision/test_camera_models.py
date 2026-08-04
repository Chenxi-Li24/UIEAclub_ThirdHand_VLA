from __future__ import annotations

import numpy as np
import pytest

from vision.camera_models import PinholeCamera, SeucmCamera, normalize_rows
from vision.types import InvalidDataError


def lumos_camera() -> SeucmCamera:
    return SeucmCamera(
        fx=392.168,
        fy=392.168,
        cx=637.761,
        cy=640.597,
        alpha=0.678979,
        beta=0.749026,
        width=1280,
        height=1280,
    )


def test_seucm_center_ray_maps_to_principal_point():
    camera = lumos_camera()
    uv, valid = camera.project(np.array([[0.0, 0.0, 1.0]]))
    np.testing.assert_allclose(uv, [[camera.cx, camera.cy]], atol=1e-12)
    assert valid.tolist() == [True]
    ray, valid = camera.unproject(uv)
    np.testing.assert_allclose(ray, [[0.0, 0.0, 1.0]], atol=1e-12)
    assert valid.tolist() == [True]


def test_seucm_project_unproject_round_trip():
    camera = lumos_camera()
    rays = normalize_rows(
        np.array(
            [
                [0.0, 0.0, 1.0],
                [0.3, -0.2, 0.9327379],
                [-0.65, 0.25, 0.72],
                [0.7, 0.6, 0.4],
            ]
        )
    )
    uv, projected = camera.project(rays)
    recovered, unprojected = camera.unproject(uv)
    assert projected.all() and unprojected.all()
    angular_error = np.arccos(np.clip(np.sum(recovered * rays, axis=1), -1.0, 1.0))
    assert angular_error.max() < 2e-6


def test_seucm_rejects_behind_domain_nonfinite_and_outside_image():
    camera = lumos_camera()
    uv, valid = camera.project(
        np.array(
            [
                [0.0, 0.0, -1.0],
                [np.nan, 0.0, 1.0],
                [100.0, 0.0, 0.01],
            ]
        )
    )
    assert valid.tolist() == [False, False, False]
    assert np.isnan(uv[0]).all()
    assert np.isnan(uv[1]).all()


def test_seucm_unproject_rejects_outside_image_and_invalid_shape():
    camera = lumos_camera()
    rays, valid = camera.unproject(np.array([[-1.0, 100.0], [100.0, 2000.0]]))
    assert not valid.any()
    assert np.isnan(rays).all()
    with pytest.raises(InvalidDataError):
        camera.unproject(np.array([1.0, 2.0]))


def test_pinhole_depth_is_z_not_euclidean_range():
    camera = PinholeCamera(600.0, 600.0, 320.0, 240.0, 640, 480)
    point = camera.deproject_z(np.array([[620.0, 240.0]]), np.array([1.0]))
    np.testing.assert_allclose(point, [[0.5, 0.0, 1.0]])
    assert np.linalg.norm(point[0]) == pytest.approx(np.sqrt(1.25))


def test_pinhole_project_deproject_round_trip():
    camera = PinholeCamera(600.0, 610.0, 320.0, 240.0, 640, 480)
    points = np.array([[0.1, -0.2, 1.0], [-0.3, 0.1, 2.0]])
    uv, valid = camera.project(points)
    recovered = camera.deproject_z(uv, points[:, 2])
    assert valid.all()
    np.testing.assert_allclose(recovered, points, atol=1e-12)


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: PinholeCamera(0.0, 1.0, 0.0, 0.0, 10, 10),
        lambda: PinholeCamera(1.0, 1.0, 0.0, 0.0, 0, 10),
        lambda: SeucmCamera(1.0, 1.0, 0.0, 0.0, 1.0, 0.5, 10, 10),
        lambda: SeucmCamera(1.0, 1.0, 0.0, 0.0, 0.5, -0.1, 10, 10),
    ],
)
def test_camera_parameters_are_validated(constructor):
    with pytest.raises(InvalidDataError):
        constructor()

