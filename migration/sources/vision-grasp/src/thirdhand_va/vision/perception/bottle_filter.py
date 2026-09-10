"""Fail-closed validation for generic bottle instance masks."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate
from thirdhand_va.vision.perception.interfaces import RawCandidate


@dataclass(frozen=True, slots=True)
class BottleShapeEvaluation:
    """Inspectable result of the conservative 2-D bottle profile gate."""

    allowed: bool
    mask_bbox_xyxy: tuple[int, int, int, int] | None
    height_px: int
    width_px: int
    aspect_ratio: float | None
    neck_median_width_px: float | None
    body_median_width_px: float | None
    neck_body_ratio: float | None
    near_frame_edge: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe metrics for standalone diagnostics."""

        return asdict(self)


class BottleCandidateFilter:
    """Convert generic bottle detections into geometry-safe candidates."""

    def __init__(self, config: VisionConfig) -> None:
        self.config = config

    def filter(
        self,
        rgb: NDArray[np.uint8],
        raw_candidates: tuple[RawCandidate, ...],
    ) -> tuple[MaskCandidate, ...]:
        image = np.asarray(rgb)
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("rgb must have shape (height, width, 3)")
        results: list[MaskCandidate] = []
        for item in raw_candidates:
            if item.prompt_label != "bottle":
                continue
            reasons: list[str] = []
            if item.score < self.config.min_bottle_score:
                reasons.append("bottle_score_below_threshold")
            if item.mask is None or item.mask.shape != image.shape[:2]:
                safe_mask = np.zeros(image.shape[:2], dtype=bool)
                reasons.append("mask_missing_or_misaligned")
            else:
                safe_mask = item.mask
                if int(safe_mask.sum()) < self.config.min_mask_pixels:
                    reasons.append("mask_too_small")
                shape = evaluate_bottle_shape(safe_mask, self.config)
                if not shape.allowed:
                    reasons.extend(shape.blockers)
                    reasons.append("container_type_not_bottle")
            results.append(
                MaskCandidate(
                    detection_id=item.detection_id,
                    label="bottle",
                    score=item.score,
                    bbox_xyxy=item.bbox_xyxy,
                    mask=safe_mask,
                    authorized=not reasons,
                    reasons=tuple(reasons),
                    descriptor=item.descriptor,
                )
            )
        return tuple(results)


def evaluate_bottle_shape(
    mask: NDArray[np.bool_],
    config: VisionConfig,
) -> BottleShapeEvaluation:
    """Measure one mask and explain every conservative shape rejection."""

    image_mask = np.asarray(mask, dtype=bool)
    if image_mask.ndim != 2:
        raise ValueError("mask must be two-dimensional")
    rows, columns = np.nonzero(image_mask)
    if rows.size == 0:
        return BottleShapeEvaluation(
            allowed=False,
            mask_bbox_xyxy=None,
            height_px=0,
            width_px=0,
            aspect_ratio=None,
            neck_median_width_px=None,
            body_median_width_px=None,
            neck_body_ratio=None,
            near_frame_edge=False,
            blockers=("bottle_mask_empty",),
        )
    top, bottom = int(rows.min()), int(rows.max()) + 1
    left, right = int(columns.min()), int(columns.max()) + 1
    height, width = bottom - top, right - left
    aspect = None if width <= 0 else height / width
    edge_margin_px = 2
    near_frame_edge = (
        top <= edge_margin_px
        or left <= edge_margin_px
        or bottom >= image_mask.shape[0] - edge_margin_px
        or right >= image_mask.shape[1] - edge_margin_px
    )
    row_widths = image_mask[top:bottom, left:right].sum(axis=1).astype(np.float64)
    neck = row_widths[: max(1, int(round(height * 0.25)))]
    body_start = min(height - 1, int(round(height * 0.45)))
    body_end = min(height, max(body_start + 1, int(round(height * 0.85))))
    neck = neck[neck > 0]
    body = row_widths[body_start:body_end]
    body = body[body > 0]
    neck_width = None if not neck.size else float(np.median(neck))
    body_width = None if not body.size else float(np.median(body))
    neck_body_ratio = (
        None
        if neck_width is None or body_width is None or body_width <= 0
        else neck_width / body_width
    )
    touches_frame_edge = (
        top == 0
        or left == 0
        or bottom == image_mask.shape[0]
        or right == image_mask.shape[1]
    )
    aspect_invalid = aspect is None or not (
        config.min_bottle_aspect_ratio
        <= aspect
        <= config.max_bottle_aspect_ratio
    )
    profile_unusable = neck_body_ratio is None
    profile_inverted = (
        neck_body_ratio is not None
        and neck_body_ratio > config.max_neck_body_ratio
    )
    blockers: list[str] = []
    if touches_frame_edge or (
        near_frame_edge and (aspect_invalid or profile_unusable or profile_inverted)
    ):
        blockers.append("bottle_mask_truncated_at_frame_edge")
    if aspect_invalid:
        blockers.append("bottle_aspect_out_of_range")
    if profile_unusable:
        blockers.append("bottle_profile_unusable")
    elif profile_inverted:
        blockers.append("bottle_profile_inverted_or_occluded")
    return BottleShapeEvaluation(
        allowed=not blockers,
        mask_bbox_xyxy=(left, top, right, bottom),
        height_px=height,
        width_px=width,
        aspect_ratio=aspect,
        neck_median_width_px=neck_width,
        body_median_width_px=body_width,
        neck_body_ratio=neck_body_ratio,
        near_frame_edge=near_frame_edge,
        blockers=tuple(blockers),
    )


def bottle_shape_passes(mask: NDArray[np.bool_], config: VisionConfig) -> bool:
    """Backward-compatible boolean wrapper around the inspectable gate."""

    return evaluate_bottle_shape(mask, config).allowed
