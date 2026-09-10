"""Structural protocol and validation for instance feature encoders."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol, runtime_checkable

import numpy as np

from thirdhand_vision.core.errors import ModelContractError


def normalized_descriptor(value: Any) -> np.ndarray:
    descriptor = np.asarray(value, dtype=float)
    if descriptor.ndim != 1 or not len(descriptor) or not np.isfinite(descriptor).all():
        raise ModelContractError("descriptor must be a finite non-empty vector")
    norm = float(np.linalg.norm(descriptor))
    if not np.isfinite(norm) or norm <= 0.0:
        raise ModelContractError("descriptor norm must be finite and positive")
    result = np.array(descriptor / norm, copy=True)
    result.setflags(write=False)
    return result


@runtime_checkable
class FeatureEncoder(Protocol):
    model_id: str

    def encode(self, image_rgb: Any, masks: Iterable[Any]) -> Sequence[np.ndarray]:
        """Return one normalized descriptor per native-image mask."""
        raise NotImplementedError

