"""Fail-closed identity and bottle-shape gate for the fixed Coke bottle."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate

from .interfaces import RawCandidate
from .references import ReferenceBank, ReferenceError

_POSITIVE = "coca-cola plastic bottle"
_COMPETITORS = {
    "pepsi bottle",
    "water bottle",
    "ordinary bottle",
    "unbranded bottle",
    "coca-cola can",
}


class FixedBottleVerifier:
    def __init__(
        self,
        config: VisionConfig,
        references: ReferenceBank,
    ) -> None:
        self.config = config
        self.references = references

    def verify(
        self,
        rgb: NDArray[np.uint8],
        raw_candidates: tuple[RawCandidate, ...],
    ) -> tuple[MaskCandidate, ...]:
        image = np.asarray(rgb)
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("rgb must have shape (height, width, 3)")
        competitors = [
            item for item in raw_candidates if item.prompt_label in _COMPETITORS
        ]
        results = []
        for item in raw_candidates:
            if item.prompt_label != _POSITIVE:
                continue
            reasons: list[str] = []
            mask = item.mask
            if item.score < self.config.min_coke_score:
                reasons.append("coke_score_below_threshold")
            if mask is None or mask.shape != image.shape[:2]:
                reasons.append("sam_mask_missing_or_misaligned")
                safe_mask = np.zeros(image.shape[:2], dtype=bool)
            else:
                safe_mask = mask
                if int(mask.sum()) < self.config.min_mask_pixels:
                    reasons.append("sam_mask_too_small")
                if not _bottle_shape_passes(mask, self.config):
                    reasons.append("container_type_not_bottle")

            strongest = max(
                (
                    other.score
                    for other in competitors
                    if _box_iou(item.bbox_xyxy, other.bbox_xyxy)
                    >= self.config.competitor_iou
                ),
                default=None,
            )
            if (
                strongest is not None
                and item.score - strongest < self.config.min_competitor_margin
            ):
                reasons.append("competitor_margin_too_small")

            if len(self.references) == 0:
                reasons.append("fixed_reference_missing")
            elif item.descriptor is None:
                reasons.append("fixed_reference_mismatch")
            else:
                try:
                    similarity = self.references.max_similarity(item.descriptor)
                except ReferenceError:
                    similarity = None
                if (
                    similarity is None
                    or similarity < self.config.min_reference_similarity
                ):
                    reasons.append("fixed_reference_mismatch")
            results.append(
                MaskCandidate(
                    detection_id=item.detection_id,
                    label=item.prompt_label,
                    score=item.score,
                    bbox_xyxy=item.bbox_xyxy,
                    mask=safe_mask,
                    authorized=not reasons,
                    reasons=tuple(reasons),
                )
            )
        return tuple(results)


def _bottle_shape_passes(mask: NDArray[np.bool_], config: VisionConfig) -> bool:
    rows, columns = np.nonzero(mask)
    if rows.size == 0:
        return False
    top, bottom = int(rows.min()), int(rows.max()) + 1
    left, right = int(columns.min()), int(columns.max()) + 1
    height = bottom - top
    width = right - left
    if width <= 0:
        return False
    aspect = height / width
    if not config.min_bottle_aspect_ratio <= aspect <= config.max_bottle_aspect_ratio:
        return False
    cropped = mask[top:bottom, left:right]
    row_widths = cropped.sum(axis=1).astype(np.float64)
    neck_end = max(1, int(round(height * 0.25)))
    body_start = min(height - 1, int(round(height * 0.45)))
    body_end = max(body_start + 1, int(round(height * 0.85)))
    neck = row_widths[:neck_end]
    body = row_widths[body_start:body_end]
    neck = neck[neck > 0]
    body = body[body > 0]
    if neck.size == 0 or body.size == 0:
        return False
    neck_body_ratio = float(np.median(neck) / np.median(body))
    return neck_body_ratio <= config.max_neck_body_ratio


def _box_iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    intersection = max(0.0, min(lx1, rx1) - max(lx0, rx0)) * max(
        0.0, min(ly1, ry1) - max(ly0, ry0)
    )
    left_area = max(0.0, lx1 - lx0) * max(0.0, ly1 - ly0)
    right_area = max(0.0, rx1 - rx0) * max(0.0, ry1 - ry0)
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0
