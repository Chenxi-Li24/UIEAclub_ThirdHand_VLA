"""
ArUco marker detector — detects markers, estimates 3D pose via solvePnP,
and converts to robot base coordinates.
"""

import cv2
import numpy as np

from ...utils.types import Detection, Pose
from .base import BaseDetector


class ArucoDetector(BaseDetector):
    """Detect ArUco markers and compute 3D pose in camera/base frame."""

    # OpenCV dictionary name → enum
    DICT_MAP = {
        "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
        "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
        "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
        "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
        "DICT_6X6_50": cv2.aruco.DICT_6X6_50,
        "DICT_6X6_100": cv2.aruco.DICT_6X6_100,
        "DICT_7X7_50": cv2.aruco.DICT_7X7_50,
    }

    def __init__(self, dictionary="DICT_4X4_50", marker_size_m=0.05,
                 transforms=None):
        dict_id = self.DICT_MAP.get(dictionary, cv2.aruco.DICT_4X4_50)
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(dict_id)
        self.detector_params = cv2.aruco.DetectorParameters()
        self.marker_size_m = marker_size_m
        self.transforms = transforms  # CoordinateTransforms instance

        # 3D corner points of marker (in marker frame)
        half = marker_size_m / 2
        self._obj_points = np.array([
            [-half, -half, 0],
            [ half, -half, 0],
            [ half,  half, 0],
            [-half,  half, 0],
        ], dtype=np.float64)

        self.last_corners = []
        self.last_ids = None

    def detect(self, image: np.ndarray) -> list[Detection]:
        """Detect ArUco markers and estimate pose. Returns list of Detection."""
        if image is None:
            return []

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # OpenCV 4.7+ / 5.x: use ArucoDetector class
        if hasattr(cv2.aruco, 'ArucoDetector'):
            aruco_detector = cv2.aruco.ArucoDetector(
                self.aruco_dict, self.detector_params
            )
            corners, ids, rejected = aruco_detector.detectMarkers(gray)
        else:
            # OpenCV < 4.7: legacy API
            corners, ids, rejected = cv2.aruco.detectMarkers(
                gray, self.aruco_dict, parameters=self.detector_params
            )
        corners = list(corners)

        self.last_corners = corners
        self.last_ids = ids

        if ids is None:
            return []

        results = []
        for i, (corner, marker_id) in enumerate(zip(corners, ids)):
            c = corner.reshape(4, 2)
            center = tuple(c.mean(axis=0).astype(int))

            # solvePnP for pose in camera frame
            pose_cam = None
            rvec, tvec = None, None
            if self.K is not None:
                success, rvec, tvec = cv2.solvePnP(
                    self._obj_points, c.astype(np.float64),
                    self.K, self.dist if hasattr(self, 'dist') else None,
                    flags=cv2.SOLVEPNP_IPPE_SQUARE
                )
                if success:
                    t = tvec.flatten()
                    r, _ = cv2.Rodrigues(rvec)
                    # Rotation to Euler (approximate)
                    pose_cam = Pose(
                        position=(float(t[0]), float(t[1]), float(t[2])),
                        orientation=(0.0, 0.0, 0.0)
                    )

            # Convert to base frame if transforms available
            pose_base = None
            if pose_cam is not None and self.transforms is not None:
                point_base = self.transforms.camera_to_base(
                    np.array(pose_cam.position)
                )
                pose_base = Pose(
                    position=(float(point_base[0]), float(point_base[1]),
                              float(point_base[2])),
                    orientation=pose_cam.orientation
                )

            results.append(Detection(
                id=int(marker_id[0]),
                label=f"aruco_{marker_id[0]}",
                confidence=1.0,
                corners_2d=[(float(x), float(y)) for x, y in corner.reshape(4, 2)],
                center_pixel=center,
                pose_camera=pose_cam,
                pose_base=pose_base,
            ))

        return results

    def draw(self, image: np.ndarray, detections: list[Detection]) -> np.ndarray:
        """Draw detection boxes, IDs, and pose axes."""
        out = image.copy()
        if self.last_corners and self.last_ids is not None and len(self.last_corners) > 0:
            cv2.aruco.drawDetectedMarkers(out, self.last_corners, self.last_ids)

        for det in detections:
            if det.pose_camera is not None and self.K is not None:
                # Draw pose axes
                rvec = np.zeros((3, 1))  # simplified — use actual rvec from detect
                tvec = np.array(det.pose_camera.position).reshape(3, 1)
                cv2.drawFrameAxes(out, self.K, None, rvec, tvec,
                                  self.marker_size_m * 0.7)

            # Draw label
            cv2.putText(out, f"ID:{det.id}",
                        (det.center_pixel[0] - 20, det.center_pixel[1] - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        return out

    def get_marker_center(self, marker_id: int) -> tuple | None:
        """Get pixel center of a specific marker from last detection."""
        if self.last_ids is None:
            return None
        for corner, mid in zip(self.last_corners, self.last_ids):
            if mid[0] == marker_id:
                c = corner.reshape(4, 2).mean(axis=0)
                return (int(c[0]), int(c[1]))
        return None

    def set_camera_matrix(self, K: np.ndarray, dist: np.ndarray = None):
        self.K = K
        self.dist = dist if dist is not None else np.zeros(4)
