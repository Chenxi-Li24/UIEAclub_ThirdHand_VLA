"""Dependency-light interfaces between learned perception and safety gates."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


def _readonly_optional(
    value: object | None,
    *,
    dtype: np.dtype | type,
) -> NDArray | None:
    if value is None:
        return None
    array = np.array(value, dtype=dtype, copy=True)
    array.setflags(write=False)
    return array


@dataclass(frozen=True, slots=True)
class RawCandidate:
    detection_id: int
    prompt_label: str
    score: float
    bbox_xyxy: tuple[float, float, float, float]
    mask: NDArray[np.bool_] | None
    descriptor: NDArray[np.float32] | None

    def __post_init__(self) -> None:
        bbox = tuple(float(value) for value in self.bbox_xyxy)
        if len(bbox) != 4 or not np.isfinite(bbox).all():
            raise ValueError("bbox_xyxy must contain four finite values")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be in [0, 1]")
        mask = _readonly_optional(self.mask, dtype=np.bool_)
        descriptor = _readonly_optional(self.descriptor, dtype=np.float32)
        if mask is not None and mask.ndim != 2:
            raise ValueError("candidate mask must be two-dimensional")
        if descriptor is not None and descriptor.ndim != 1:
            raise ValueError("candidate descriptor must be one-dimensional")
        object.__setattr__(
            self,
            "prompt_label",
            canonical_prompt_label(self.prompt_label),
        )
        object.__setattr__(self, "bbox_xyxy", bbox)
        object.__setattr__(self, "mask", mask)
        object.__setattr__(self, "descriptor", descriptor)


class PerceptionBackend(Protocol):
    def infer(self, rgb: NDArray[np.uint8]) -> tuple[RawCandidate, ...]:
        """Return prompt-labelled boxes with SAM masks and appearance descriptors."""

    def model_provenance(self) -> dict[str, str]:
        """Return model identifiers and runtime versions for evidence records."""


def canonical_prompt_label(label: str) -> str:
    normalized = " ".join(str(label).strip().lower().split())
    normalized = re.sub(r"\s*[-–—]\s*", "-", normalized)
    if "coca-cola" in normalized and "can" in normalized:
        return "coca-cola can"
    if (
        "coca-cola" in normalized
        and "plastic" in normalized
        and "bottle" in normalized
    ):
        return "coca-cola plastic bottle"
    if "pepsi" in normalized and "bottle" in normalized:
        return "pepsi bottle"
    if "water" in normalized and "bottle" in normalized:
        return "water bottle"
    if "ordinary" in normalized and "bottle" in normalized:
        return "ordinary bottle"
    return normalized
