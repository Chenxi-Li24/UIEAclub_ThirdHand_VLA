"""Instance-segmentation protocols and optional model adapters."""

from .base import InstanceSegmenter
from .rtmdet import RTMDetSegmenter, detections_from_mmdet, validate_model_labels

__all__ = [
    "InstanceSegmenter",
    "RTMDetSegmenter",
    "detections_from_mmdet",
    "validate_model_labels",
]

