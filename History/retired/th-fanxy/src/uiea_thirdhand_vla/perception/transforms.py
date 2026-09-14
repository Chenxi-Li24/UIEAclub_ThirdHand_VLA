"""
Coordinate transforms — pixel ↔ camera ↔ robot base.
Supports both depth-based back-projection and desktop plane homography.
"""


import cv2
import numpy as np


class CoordinateTransforms:
    """SE(3) coordinate transforms for camera-to-robot conversion."""

    def __init__(self, camera_matrix=None, hand_eye_matrix=None,
                 seucm_params=None, desktop_z=0.0):
        self.K = camera_matrix if camera_matrix is not None else np.eye(3)
        self.T_base_cam = hand_eye_matrix if hand_eye_matrix is not None else np.eye(4)
        self.seucm = seucm_params or {}
        self.desktop_z = desktop_z  # fixed Z height for plane mapping

        # Desktop homography (pixel → base XY)
        self.H_desktop: np.ndarray | None = None

    # ---- Pixel ↔ Camera (3D) ----

    def pixel_to_camera(self, u: float, v: float, depth: float) -> np.ndarray:
        """
        Back-project pixel + depth to 3D point in camera frame.
        Uses SEUCM model for direction, scales by depth.
        """
        ray, _ = self._unproject_pixel(u, v)
        return ray * depth

    def camera_to_pixel(self, point_cam: np.ndarray) -> tuple[float, float]:
        """Project 3D camera-frame point to pixel."""
        pixels, valid = self._project_points(point_cam.reshape(1, 3))
        return (pixels[0, 0], pixels[0, 1]) if valid[0] else (0, 0)

    # ---- Camera ↔ Robot Base ----

    def camera_to_base(self, point_cam: np.ndarray) -> np.ndarray:
        """Transform point from camera frame to robot base frame."""
        return self._apply_transform(self.T_base_cam, point_cam)

    def base_to_camera(self, point_base: np.ndarray) -> np.ndarray:
        """Transform point from robot base frame to camera frame."""
        T_cam_base = self._invert_pose(self.T_base_cam)
        return self._apply_transform(T_cam_base, point_base)

    # ---- Pixel → Robot Base (main pipeline) ----

    def pixel_to_base(self, u: float, v: float, depth: float) -> np.ndarray:
        """Full pipeline: pixel + depth → camera 3D → robot base 3D."""
        point_cam = self.pixel_to_camera(u, v, depth)
        return self.camera_to_base(point_cam)

    def pixel_to_base_plane(self, u: float, v: float,
                            plane_z: float | None = None) -> tuple[float, float, float]:
        """
        Project pixel to a horizontal plane at known Z height.
        This is the 'basic mode' — no depth sensor needed.
        Uses SEUCM ray intersection with Z=plane_z plane.
        """
        z = plane_z if plane_z is not None else self.desktop_z
        ray, _ = self._unproject_pixel(u, v)

        # Intersect ray with plane at camera-frame Z
        if abs(ray[2]) < 1e-10:
            return 0.0, 0.0, z

        scale = z / ray[2] if ray[2] > 0 else 0
        point_cam = ray * scale
        point_base = self.camera_to_base(point_cam)
        return float(point_base[0]), float(point_base[1]), float(point_base[2])

    # ---- Desktop Homography (simplest mode) ----

    def calibrate_desktop_homography(self, pixel_points: np.ndarray,
                                     base_xy_points: np.ndarray) -> np.ndarray:
        """
        Compute homography from pixel coords to base frame XY.
        pixel_points: (N, 2) marker centers in image
        base_xy_points: (N, 2) corresponding XY in robot base frame
        Returns 3×3 homography matrix.
        """
        self.H_desktop, _ = cv2.findHomography(
            pixel_points.astype(np.float64),
            base_xy_points.astype(np.float64),
            method=cv2.RANSAC
        )
        return self.H_desktop

    def pixel_to_base_homography(self, u: float, v: float) -> tuple[float, float]:
        """Convert pixel to base XY using calibrated homography."""
        if self.H_desktop is None:
            raise RuntimeError(
                "Homography not calibrated. Call calibrate_desktop_homography first."
            )
        p = np.array([u, v, 1.0])
        xy = self.H_desktop @ p
        xy = xy[:2] / xy[2]
        return float(xy[0]), float(xy[1])

    # ---- Hand-Eye ----

    def set_hand_eye(self, matrix: np.ndarray):
        """Set T_base_camera (4×4 hand-eye transform)."""
        self.T_base_cam = matrix.copy()

    def calibrate_hand_eye(self, T_base_ee_list, T_camera_marker_list) -> np.ndarray:
        """
        Solve AX=XB for T_base_camera.
        T_base_ee: robot end-effector in base frame
        T_camera_marker: marker in camera frame (from ArUco solvePnP)
        Returns T_base_camera.
        """
        R_ee = [T[:3, :3] for T in T_base_ee_list]
        t_ee = [T[:3, 3].reshape(3, 1) for T in T_base_ee_list]
        R_marker = [T[:3, :3] for T in T_camera_marker_list]
        t_marker = [T[:3, 3].reshape(3, 1) for T in T_camera_marker_list]

        R_cam, t_cam = cv2.calibrateHandEye(
            R_ee, t_ee, R_marker, t_marker,
            method=cv2.CALIB_HAND_EYE_TSAI
        )
        self.T_base_cam = np.eye(4)
        self.T_base_cam[:3, :3] = R_cam
        self.T_base_cam[:3, 3] = t_cam.flatten()
        return self.T_base_cam

    # ---- SEUCM helpers ----

    def _unproject_pixel(self, u: float, v: float) -> tuple[np.ndarray, bool]:
        """Unproject single pixel to unit direction vector (SEUCM)."""
        alpha = self.seucm.get("alpha", 0.679)
        beta = self.seucm.get("beta", 0.749)
        fx, fy = self.K[0, 0], self.K[1, 1]
        u0, v0 = self.K[0, 2], self.K[1, 2]

        xn = (u - u0) / fx
        yn = (v - v0) / fy
        r2 = xn ** 2 + yn ** 2

        a2 = alpha ** 2
        a2b = a2 - beta
        if a2b > 0 and r2 >= 1.0 / a2b:
            return np.array([xn, yn, 1.0]), False

        sqrt_term = np.sqrt(max(1 - a2b * r2, 0))
        denom = alpha * sqrt_term + (1 - alpha)
        denom = max(denom, 1e-10)

        Z = (1 - a2 * beta * r2) / denom
        norm = np.sqrt(xn ** 2 + yn ** 2 + Z ** 2)
        norm = max(norm, 1e-10)

        return np.array([xn / norm, yn / norm, Z / norm]), True

    def _project_points(self, points_3d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Project 3D points to pixels (SEUCM)."""
        alpha = self.seucm.get("alpha", 0.679)
        beta = self.seucm.get("beta", 0.749)
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

    # ---- SE(3) helpers ----

    @staticmethod
    def _apply_transform(T: np.ndarray, point: np.ndarray) -> np.ndarray:
        """Apply 4×4 transform to 3D point."""
        p = np.append(point, 1.0)
        return (T @ p)[:3]

    @staticmethod
    def _invert_pose(T: np.ndarray) -> np.ndarray:
        """Invert 4×4 homogeneous transform."""
        T_inv = np.eye(4)
        R = T[:3, :3]
        t = T[:3, 3]
        T_inv[:3, :3] = R.T
        T_inv[:3, 3] = -R.T @ t
        return T_inv
