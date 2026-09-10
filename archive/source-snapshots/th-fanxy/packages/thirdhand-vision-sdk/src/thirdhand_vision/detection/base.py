"""Structural protocol for caller-supplied instance segmenters."""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable

from thirdhand_vision.core.types import InstanceDetection


@runtime_checkable
class InstanceSegmenter(Protocol):
    def predict(self, image_rgb: Any) -> Sequence[InstanceDetection]:
        """Return native-image detections and boolean instance masks."""
        raise NotImplementedError

