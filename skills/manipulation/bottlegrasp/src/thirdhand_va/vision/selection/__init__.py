"""Spatial ordinal selection and persistent target identity locking."""

from .ordinal_selector import (
    SelectionRequest,
    SelectionResult,
    SelectionSide,
    SpatialBottleSelector,
    mask_centroid,
)
from .target_lock import TargetLock
from .stable_selector import (
    StableBottleSelector,
    StableSelectionRequest,
    StableSelectionResult,
)

__all__ = [
    "SelectionRequest",
    "SelectionResult",
    "SelectionSide",
    "SpatialBottleSelector",
    "StableBottleSelector",
    "StableSelectionRequest",
    "StableSelectionResult",
    "TargetLock",
    "mask_centroid",
]
