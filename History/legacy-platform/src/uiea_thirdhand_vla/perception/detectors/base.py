"""
Base detector interface  all detectors implement this abstract class.
"""

from abc import ABC, abstractmethod
from ..utils.types import Detection


class BaseDetector(ABC):
    """Abstract interface for all object detectors."""

    @abstractmethod
    def detect(self, image) -> list:
        """Detect objects in RGB image. Returns list of Detection."""
        ...

    @abstractmethod
    def draw(self, image, detections):
        """Draw detection overlays on image."""
        ...

    def set_camera_matrix(self, K, dist):
        """Set camera intrinsics for 3D pose estimation."""
        self.K = K
        self.dist = dist
