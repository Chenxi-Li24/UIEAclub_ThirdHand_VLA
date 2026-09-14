"""
YOLO-based object detector using Ultralytics.

Used after ArUco baseline is stable (Week 2+).
"""

from .base import BaseDetector


class YoloDetector(BaseDetector):
    """YOLO object detection for markerless picking."""

    def __init__(self, model_path="yolov8n.pt", confidence=0.5):
        self.model_path = model_path
        self.confidence = confidence

    def detect(self, image):
        return []  # TODO: implement

    def draw(self, image, detections):
        return image  # TODO: implement
