"""
Camera calibration — SEUCM model for Lumos Ego ultra-wide-angle camera.
Supports load/save, undistort, and projection/unprojection.
"""

import json

import cv2
import numpy as np


class CameraCalibration:
    """SEUCM camera intrinsics with load/save and undistortion."""

    def __init__(self, camera_matrix=None, dist_coeffs=None,
                 camera_model="seucm", seucm_params=None):
        self.K = camera_matrix if camera_matrix is not None else np.eye(3)
        self.dist = dist_coeffs if dist_coeffs is not None else np.zeros(4)
        self.model = camera_model  # "seucm" | "pinhole" | "fisheye"
        self.seucm_params = seucm_params or {}
        self.map_x = None
        self.map_y = None
        self._map_initialized = False

    # ---- SEUCM projection / unprojection ----

    def project(self, points_3d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        Project 3D points (in camera frame) to pixel coordinates.
        points_3d: (N, 3)
        Returns: (N, 2) pixels, (N,) valid mask
        """
        alpha = self.seucm_params.get("alpha", 0.679)
        beta = self.seucm_params.get("beta", 0.749)
        fx, fy = self.K[0, 0], self.K[1, 1]
        u0, v0 = self.K[0, 2], self.K[1, 2]

        X, Y, Z = points_3d[:, 0], points_3d[:, 1], points_3d[:, 2]
        valid = Z > 0

        r2_xy = X ** 2 + Y ** 2
        d = np.sqrt(beta * r2_xy + Z ** 2)
        s = alpha * d + (1 - alpha) * Z
        s = np.where(s > 1e-10, s, 1e-10)

        u = fx * X / s + u0
        v = fy * Y / s + v0
        return np.stack([u, v], axis=-1), valid

    def unproject(self, pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        Unproject pixels to unit-sphere direction vectors.
        pixels: (N, 2)
        Returns: (N, 3) unit vectors, (N,) valid mask
        """
        alpha = self.seucm_params.get("alpha", 0.679)
        beta = self.seucm_params.get("beta", 0.749)
        fx, fy = self.K[0, 0], self.K[1, 1]
        u0, v0 = self.K[0, 2], self.K[1, 2]

        xn = (pixels[:, 0] - u0) / fx
        yn = (pixels[:, 1] - v0) / fy
        r2 = xn ** 2 + yn ** 2

        a2 = alpha ** 2
        a2b = a2 - beta
        a2beta = a2 * beta

        valid = np.ones(len(pixels), dtype=bool)
        if a2b > 0:
            valid = r2 < (1.0 / a2b)

        sqrt_term = np.sqrt(np.maximum(1 - a2b * r2, 0))
        denom = alpha * sqrt_term + (1 - alpha)
        denom = np.where(denom > 1e-10, denom, 1e-10)

        Z = (1 - a2beta * r2) / denom
        norm = np.sqrt(xn ** 2 + yn ** 2 + Z ** 2)
        norm = np.where(norm > 1e-10, norm, 1e-10)

        return np.stack([xn / norm, yn / norm, Z / norm], axis=-1), valid

    # ---- Undistort (SEUCM → pinhole) ----

    def undistort(self, image: np.ndarray) -> np.ndarray:
        """Undistort SEUCM image to approximate pinhole model."""
        if not self._map_initialized:
            self._build_undistort_maps(image.shape[1], image.shape[0])
        return cv2.remap(image, self.map_x, self.map_y, cv2.INTER_LINEAR)

    def _build_undistort_maps(self, w: int, h: int):
        """Precompute undistortion remap for given image size."""
        ys, xs = np.mgrid[0:h, 0:w]
        pixels = np.stack([xs.ravel(), ys.ravel()], axis=-1).astype(np.float64)

        rays, valid = self.unproject(pixels)

        # Virtual pinhole camera pointing forward
        fx_v = self.K[0, 0]
        fy_v = self.K[1, 1]
        u0_v = w / 2.0
        v0_v = h / 2.0

        Z = rays[:, 2]
        Z = np.where(np.abs(Z) > 1e-10, Z, np.sign(Z) * 1e-10)

        u_new = (fx_v * rays[:, 0] / Z + u0_v).reshape(h, w).astype(np.float32)
        v_new = (fy_v * rays[:, 1] / Z + v0_v).reshape(h, w).astype(np.float32)

        self.map_x = u_new
        self.map_y = v_new
        self._map_initialized = True

    # ---- Persistence ----

    @classmethod
    def load(cls, path: str) -> "CameraCalibration":
        """Load calibration from JSON file."""
        with open(path) as f:
            data = json.load(f)
        K = np.array(data.get("K", [[1, 0, 0], [0, 1, 0], [0, 0, 1]]))
        dist = np.array(data.get("dist", [0, 0, 0, 0]))
        model = data.get("model", "seucm")
        seucm = data.get("seucm_params", {})
        return cls(K, dist, model, seucm)

    def save(self, path: str):
        """Save calibration to JSON file."""
        data = {
            "K": self.K.tolist(),
            "dist": self.dist.tolist(),
            "model": self.model,
            "seucm_params": self.seucm_params,
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    # ---- Factory ----

    @classmethod
    def for_lumos_ego_std(cls) -> "CameraCalibration":
        """Create calibration for Lumos Ego STD (SN: 250801DR48FB26001402)."""
        K = np.array([
            [392.168, 0, 637.761],
            [0, 392.168, 640.597],
            [0, 0, 1]
        ], dtype=np.float64)
        return cls(
            camera_matrix=K,
            dist_coeffs=np.zeros(4),
            camera_model="seucm",
            seucm_params={
                "alpha": 0.678979,
                "beta": 0.749026,
                "eu": 636.665,
                "ev": 639.882,
                "fx": 392.168,
                "fy": 392.168,
                "u0": 637.761,
                "v0": 640.597,
            }
        )
