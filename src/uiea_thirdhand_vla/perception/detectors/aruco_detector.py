"""
ArUco marker detector using OpenCV contrib.
"""

from .base import BaseDetector


class ArucoDetector(BaseDetector):
    """Detect ArUco markers and compute 3D pose via solvePnP."""

    def __init__(self, dictionary="DICT_4X4_50", marker_size_m=0.05):
        self.dictionary = dictionary
        self.marker_size_m = marker_size_m

    def detect(self, image):
        return []  # TODO: implement

    def draw(self, image, detections):
        return image  # TODO: implement
