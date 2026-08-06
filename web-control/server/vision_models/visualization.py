"""Read-only rendering adapter for perception, identity, depth, and grasp gates."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .contracts import ModelContractError

LOCKED_COLOUR_RGB = (255, 180, 32)
READY_COLOUR_RGB = (62, 220, 112)
TARGET_COLOUR_RGB = (82, 168, 223)
CALLOUT_LINE_STEP_PX = 12
CALLOUT_SLOT_HEIGHT_PX = 52
CALLOUT_FONT_SCALE = 0.32


def _finite_pixel(value: Any, name: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ModelContractError(f"{name} must contain two pixel coordinates")
    coordinates = np.asarray(value, dtype=float)
    if coordinates.shape != (2,) or not np.isfinite(coordinates).all():
        raise ModelContractError(f"{name} must contain two finite pixel coordinates")
    return int(round(float(coordinates[0]))), int(round(float(coordinates[1])))


def _mask_anchor(mask: np.ndarray) -> tuple[int, int]:
    rows, columns = np.nonzero(mask)
    if len(rows) == 0:
        raise ModelContractError("visualization mask must be non-empty")
    return int(round(float(np.median(columns)))), int(round(float(np.median(rows))))


def _identity_state(target: Any) -> str:
    state = getattr(target, "identity_status", "unknown")
    value = getattr(state, "value", state)
    return str(value)[:32] if value is not None else "unknown"


def _pose_text(pose: Any) -> str:
    if pose is None:
        return "XYZ --"
    xyz = np.asarray(getattr(pose, "xyz_m", None), dtype=float)
    covariance = np.asarray(getattr(pose, "covariance_m2", None), dtype=float)
    if xyz.shape != (3,) or not np.isfinite(xyz).all():
        return "XYZ --"
    if covariance.shape != (3, 3) or not np.isfinite(covariance).all():
        return f"XYZ {xyz[0]:+.3f} {xyz[1]:+.3f} {xyz[2]:+.3f} m"
    diagonal = np.diag(covariance)
    if np.any(diagonal < 0.0):
        return f"XYZ {xyz[0]:+.3f} {xyz[1]:+.3f} {xyz[2]:+.3f} m"
    sigma_mm = math.sqrt(float(np.max(diagonal))) * 1000.0
    return (
        f"XYZ {xyz[0]:+.3f} {xyz[1]:+.3f} {xyz[2]:+.3f} m"
        f" | sigma<={sigma_mm:.1f} mm"
    )


@dataclass(frozen=True)
class TargetVisual:
    """A display-only snapshot; it cannot authorize or execute robot actions."""

    detection_id: int
    identity_id: int | None
    bbox_xyxy: tuple[int, int, int, int]
    mask: np.ndarray = field(compare=False, repr=False)
    anchor_px: tuple[int, int]
    grasp_point_px: tuple[int, int] | None
    grasp_allowed: bool
    lines: tuple[str, str, str, str]
    colour_rgb: tuple[int, int, int]

    def __post_init__(self) -> None:
        mask = np.asarray(self.mask)
        if mask.ndim != 2 or mask.dtype != np.bool_ or not mask.any():
            raise ModelContractError("target visual requires a non-empty boolean mask")
        copied = np.array(mask, copy=True)
        copied.setflags(write=False)
        object.__setattr__(self, "mask", copied)


def build_target_visual(
    annotation: Any,
    target: Any,
    *,
    grasp_point_px: Any = None,
    grasp_execution_enabled: bool = False,
) -> TargetVisual:
    """Convert immutable algorithm outputs into a bounded display record."""

    if not isinstance(grasp_execution_enabled, bool):
        raise ModelContractError("grasp execution gate must be an explicit boolean")
    detection_id = int(getattr(annotation, "detection_id"))
    if int(getattr(target, "detection_id")) != detection_id:
        raise ModelContractError("annotation and target detection IDs do not match")
    mask = np.asarray(getattr(annotation, "mask", None))
    if mask.ndim != 2 or mask.dtype != np.bool_ or not mask.any():
        raise ModelContractError("visualization annotation mask is invalid")
    box = np.rint(np.asarray(getattr(annotation, "bbox_xyxy", None), dtype=float)).astype(int)
    if box.shape != (4,) or not np.isfinite(box).all():
        raise ModelContractError("visualization bounding box is invalid")

    identity_id = getattr(target, "identity_id", None)
    if identity_id is not None:
        identity_id = int(identity_id)
    identity_label = "?" if identity_id is None else str(identity_id)
    label = str(getattr(annotation, "label", "unknown"))[:64]
    score = float(getattr(annotation, "score", 0.0))
    if not math.isfinite(score):
        raise ModelContractError("visualization score must be finite")
    point = _finite_pixel(grasp_point_px, "grasp point")
    actionable = bool(getattr(target, "actionable", False))
    reasons = tuple(str(value)[:96] for value in getattr(target, "reasons", ()))

    if not actionable:
        deny_reason = reasons[0] if reasons else "perception_not_actionable"
    elif not grasp_execution_enabled:
        deny_reason = "execution_locked"
    elif point is None:
        deny_reason = "grasp_preview_unavailable"
    else:
        deny_reason = None
    allowed = deny_reason is None
    depth_points = int(getattr(target, "registered_depth_points", 0))
    lines = (
        f"ID#{identity_label} {label} {score:.2f} | {_identity_state(target)}",
        _pose_text(getattr(target, "pose", None)),
        f"DEPTH {max(0, depth_points)} | GRASP POINT "
        + ("--" if point is None else f"{point[0]},{point[1]}"),
        "GRASP YES" if allowed else f"GRASP NO | {deny_reason}",
    )
    colour = READY_COLOUR_RGB if allowed else LOCKED_COLOUR_RGB
    return TargetVisual(
        detection_id=detection_id,
        identity_id=identity_id,
        bbox_xyxy=tuple(int(value) for value in box),
        mask=mask,
        anchor_px=_mask_anchor(mask),
        grasp_point_px=point,
        grasp_allowed=allowed,
        lines=lines,
        colour_rgb=colour,
    )


def build_target_visuals(
    annotations: Iterable[Any],
    targets: Iterable[Any],
    *,
    grasp_points_px: Mapping[int, tuple[int, int]] | None = None,
    grasp_execution_enabled: bool = False,
) -> tuple[TargetVisual, ...]:
    targets_by_id = {int(target.detection_id): target for target in targets}
    points = {} if grasp_points_px is None else dict(grasp_points_px)
    visuals = []
    for annotation in annotations:
        detection_id = int(annotation.detection_id)
        target = targets_by_id.get(detection_id)
        if target is None:
            continue
        visuals.append(
            build_target_visual(
                annotation,
                target,
                grasp_point_px=points.get(detection_id),
                grasp_execution_enabled=grasp_execution_enabled,
            )
        )
    return tuple(visuals)


def _callout_origins(
    visuals: tuple[TargetVisual, ...], image_width: int, image_height: int
) -> dict[int, tuple[int, int, int]]:
    """Greedily place a bounded callout rail without overlapping text blocks."""

    available_height = max(0, image_height - 24)
    capacity = max(1, available_height // CALLOUT_SLOT_HEIGHT_PX)
    selected = sorted(visuals, key=lambda item: item.anchor_px[1])[:capacity]
    if not selected:
        return {}
    panel_on_left = float(np.median([item.anchor_px[0] for item in selected])) >= (
        image_width / 2.0
    )
    preferred_tops = [
        int(
            np.clip(
                item.anchor_px[1] - CALLOUT_SLOT_HEIGHT_PX // 2,
                2,
                max(2, image_height - CALLOUT_SLOT_HEIGHT_PX - 20),
            )
        )
        for item in selected
    ]
    tops = []
    for preferred in preferred_tops:
        tops.append(preferred if not tops else max(preferred, tops[-1] + CALLOUT_SLOT_HEIGHT_PX))
    overflow = tops[-1] + CALLOUT_SLOT_HEIGHT_PX + 20 - image_height
    if overflow > 0:
        tops = [value - overflow for value in tops]
    if tops[0] < 2:
        adjustment = 2 - tops[0]
        tops = [value + adjustment for value in tops]

    origins: dict[int, tuple[int, int, int]] = {}
    for visual, top in zip(selected, tops):
        text_width = max(
            cv2.getTextSize(
                line,
                cv2.FONT_HERSHEY_SIMPLEX,
                CALLOUT_FONT_SCALE,
                1,
            )[0][0]
            for line in visual.lines
        )
        text_x = 5 if panel_on_left else max(5, image_width - text_width - 5)
        origins[visual.detection_id] = (text_x, top + 10, text_width)
    return origins


def render_target_visuals(
    image_rgb: Any,
    visuals: Iterable[TargetVisual],
    *,
    model_ready: bool,
) -> np.ndarray:
    """Render diagnostics without mutating inputs or changing any gate state."""

    source = np.asarray(image_rgb)
    if source.ndim != 3 or source.shape[2] != 3 or source.dtype != np.uint8:
        raise ModelContractError("visualization input must be an HxWx3 uint8 RGB image")
    if not isinstance(model_ready, bool):
        raise ModelContractError("model readiness must be an explicit boolean")
    canvas = np.array(source, copy=True)
    height, width = canvas.shape[:2]
    visual_items = tuple(visuals)
    for visual in visual_items:
        if not isinstance(visual, TargetVisual) or visual.mask.shape != (height, width):
            raise ModelContractError("target visual mask must match the source image")
        colour = visual.colour_rgb
        tint = np.empty_like(canvas)
        tint[:] = colour
        blended = cv2.addWeighted(canvas, 0.80, tint, 0.20, 0.0)
        canvas[visual.mask] = blended[visual.mask]
        contours, _ = cv2.findContours(
            visual.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(canvas, contours, -1, colour, 2, cv2.LINE_AA)
        x1, y1, x2, y2 = visual.bbox_xyxy
        cv2.rectangle(canvas, (x1, y1), (x2, y2), colour, 1, cv2.LINE_AA)
        cv2.drawMarker(
            canvas,
            visual.anchor_px,
            TARGET_COLOUR_RGB,
            markerType=cv2.MARKER_CROSS,
            markerSize=10,
            thickness=1,
            line_type=cv2.LINE_AA,
        )
        if visual.grasp_point_px is not None:
            cv2.drawMarker(
                canvas,
                visual.grasp_point_px,
                READY_COLOUR_RGB if visual.grasp_allowed else LOCKED_COLOUR_RGB,
                markerType=cv2.MARKER_TILTED_CROSS,
                markerSize=13,
                thickness=2,
                line_type=cv2.LINE_AA,
            )
    callout_origins = _callout_origins(visual_items, width, height)
    for visual in visual_items:
        layout = callout_origins.get(visual.detection_id)
        if layout is None:
            continue
        text_x, text_y, text_width = layout
        background_top = max(0, text_y - 10)
        background_bottom = min(height - 1, text_y + 3 * CALLOUT_LINE_STEP_PX + 4)
        cv2.rectangle(
            canvas,
            (max(0, text_x - 3), background_top),
            (min(width - 1, text_x + text_width + 3), background_bottom),
            (5, 10, 14),
            cv2.FILLED,
        )
        callout_edge_x = text_x - 3 if text_x > visual.anchor_px[0] else text_x + text_width + 3
        cv2.line(
            canvas,
            visual.anchor_px,
            (int(np.clip(callout_edge_x, 0, width - 1)), (background_top + background_bottom) // 2),
            visual.colour_rgb,
            1,
            cv2.LINE_AA,
        )
        for index, line in enumerate(visual.lines):
            cv2.putText(
                canvas,
                line,
                (text_x, text_y + index * CALLOUT_LINE_STEP_PX),
                cv2.FONT_HERSHEY_SIMPLEX,
                CALLOUT_FONT_SCALE,
                visual.colour_rgb,
                1,
                cv2.LINE_AA,
            )
    hidden_callouts = len(visual_items) - len(callout_origins)
    if hidden_callouts > 0:
        cv2.putText(
            canvas,
            f"+{hidden_callouts} TARGET DETAILS IN STATUS PANEL",
            (6, 14),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.34,
            LOCKED_COLOUR_RGB,
            1,
            cv2.LINE_AA,
        )
    cv2.putText(
        canvas,
        ("MODEL READY" if model_ready else "MODEL UNAVAILABLE") + " | DISPLAY ONLY",
        (6, max(14, height - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        READY_COLOUR_RGB if model_ready else (255, 80, 80),
        1,
        cv2.LINE_AA,
    )
    return canvas


__all__ = [
    "TargetVisual",
    "build_target_visual",
    "build_target_visuals",
    "render_target_visuals",
]
