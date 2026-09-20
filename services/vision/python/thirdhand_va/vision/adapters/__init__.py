"""External protocol adapters exported by the Vision domain."""

from .event_publisher import LatestFramePublisher, build_detection_event
from .mjpeg_publisher import FrameProvenance, build_mjpeg_part

__all__ = [
    "FrameProvenance",
    "LatestFramePublisher",
    "build_detection_event",
    "build_mjpeg_part",
]
