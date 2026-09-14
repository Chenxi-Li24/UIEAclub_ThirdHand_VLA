"""
Camera calibration  intrinsics, undistortion, hand-eye calibration.
"""

import numpy as np


class CameraCalibration:
    def __init__(self, camera_matrix, dist_coeffs, camera_model="seucm"):
        self.K = camera_matrix
        self.dist = dist_coeffs
        self.model = camera_model

    def undistort(self, image):
        return image  # TODO: implement

    @classmethod
    def load(cls, path):
        return cls(np.eye(3), np.zeros(4))

    def save(self, path):
        pass
