"""
Coordinate transforms  SE(3) operations for camera-to-robot frame conversion.
"""

import numpy as np


class CoordinateTransforms:
    def __init__(self, camera_matrix=None, hand_eye_matrix=None):
        self.K = camera_matrix if camera_matrix is not None else np.eye(3)
        self.T_base_cam = hand_eye_matrix if hand_eye_matrix is not None else np.eye(4)

    def pixel_to_camera(self, u, v, depth):
        return np.array([0, 0, 0])  # TODO: implement

    def camera_to_base(self, point_cam):
        return point_cam  # TODO: implement

    def pixel_to_base_plane(self, u, v, plane_z=0.0):
        return 0.0, 0.0, plane_z  # TODO: implement

    def set_hand_eye(self, matrix):
        self.T_base_cam = matrix
