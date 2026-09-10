"""Select an authorized bottle by its horizontal ordinal in the camera image."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from thirdhand_va.common.contracts import MaskCandidate, SpatialRank

SelectionSide = Literal["left", "right"]


@dataclass(frozen=True, slots=True)
class SelectionRequest:
    side: SelectionSide
    ordinal: int

    def __post_init__(self) -> None:
        if self.side not in {"left", "right"}:
            raise ValueError("selection side must be left or right")
        if self.ordinal <= 0:
            raise ValueError("selection ordinal must be positive")


@dataclass(frozen=True, slots=True)
class SelectionResult:
    selected: MaskCandidate | None
    ranks: tuple[SpatialRank, ...] = ()
    reasons: tuple[str, ...] = ()


def mask_centroid(mask: np.ndarray) -> tuple[float, float]:
    rows, columns = np.nonzero(mask)
    if not rows.size:
        raise ValueError("candidate mask is empty")
    return float(columns.mean()), float(rows.mean())


class SpatialBottleSelector:
    def __init__(self, min_horizontal_gap_px: float) -> None:
        if min_horizontal_gap_px < 0:
            raise ValueError("minimum horizontal gap must be non-negative")
        self.min_horizontal_gap_px = float(min_horizontal_gap_px)

    def select(
        self,
        candidates: tuple[MaskCandidate, ...],
        request: SelectionRequest,
    ) -> SelectionResult:
        authorized = tuple(item for item in candidates if item.authorized)
        ordered = sorted(
            ((item, mask_centroid(item.mask)) for item in authorized),
            key=lambda item: item[1][0],
        )
        ranks = tuple(
            SpatialRank(item.detection_id, center, index + 1, len(ordered) - index)
            for index, (item, center) in enumerate(ordered)
        )
        gaps = [
            ordered[index + 1][1][0] - ordered[index][1][0]
            for index in range(len(ordered) - 1)
        ]
        if any(gap < self.min_horizontal_gap_px for gap in gaps):
            return SelectionResult(None, ranks, ("horizontal_order_ambiguous",))
        if request.ordinal > len(ordered):
            return SelectionResult(None, ranks, ("ordinal_out_of_range",))
        index = request.ordinal - 1 if request.side == "left" else -request.ordinal
        return SelectionResult(ordered[index][0], ranks, ())


__all__ = [
    "SelectionRequest",
    "SelectionResult",
    "SelectionSide",
    "SpatialBottleSelector",
    "mask_centroid",
]
