"""Immutable contracts at the heavy-model process boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


class ModelContractError(ValueError):
    """Raised when model input or output cannot be consumed safely."""


@dataclass(frozen=True)
class InstanceDetection:
    detection_id: int
    label: str
    score: float
    bbox_xyxy: np.ndarray = field(compare=False)
    mask: np.ndarray = field(compare=False)

    def __post_init__(self) -> None:
        score = float(self.score)
        box = np.asarray(self.bbox_xyxy, dtype=float)
        mask = np.asarray(self.mask)
        if self.detection_id < 0 or not self.label:
            raise ModelContractError("detection ID and label must be valid")
        if not np.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ModelContractError("detection score must be within [0, 1]")
        if box.shape != (4,) or not np.isfinite(box).all():
            raise ModelContractError("bbox_xyxy must be a finite four-vector")
        x1, y1, x2, y2 = box
        if x2 <= x1 or y2 <= y1:
            raise ModelContractError("bbox_xyxy must have positive area")
        if mask.ndim != 2 or mask.dtype != np.bool_:
            raise ModelContractError("instance mask must be a 2D boolean array")
        if not mask.any():
            raise ModelContractError("instance mask cannot be empty")
        height, width = mask.shape
        if x1 < 0.0 or y1 < 0.0 or x2 > width or y2 > height:
            raise ModelContractError("bbox_xyxy must remain inside the mask image")
        box_copy = np.array(box, copy=True)
        mask_copy = np.array(mask, copy=True)
        box_copy.setflags(write=False)
        mask_copy.setflags(write=False)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "bbox_xyxy", box_copy)
        object.__setattr__(self, "mask", mask_copy)


def validated_rgb_image(image_rgb: Any) -> np.ndarray:
    image = np.asarray(image_rgb)
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ModelContractError("RGB image must be a uint8 array with shape (H, W, 3)")
    if image.shape[0] < 1 or image.shape[1] < 1:
        raise ModelContractError("RGB image dimensions must be positive")
    return image
