"""Deterministic visualization of bottle selection and grasp readiness."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from thirdhand_va.common.contracts import VisionDecision

from .depth_heatmap import (
    DEFAULT_DEPTH_ALPHA,
    add_depth_legend,
    blend_registered_depth,
)


@dataclass(frozen=True, slots=True)
class RenderMetrics:
    fps: float
    latency_ms: float
    dino_ms: float | None = None
    sam_ms: float | None = None


@dataclass(frozen=True, slots=True)
class OverlayResult:
    image: NDArray[np.uint8]
    labels: frozenset[str]
    panel_lines: tuple[str, ...]


_COLORS = ((255, 110, 30), (30, 180, 255), (210, 80, 220), (80, 220, 120))
_ACTIONABLE_COLOR = (60, 220, 80)
_BLOCKED_COLOR = (230, 70, 70)
_MASK_ALPHA = 0.20


def render_overlay(
    rgb: NDArray[np.uint8],
    decision: VisionDecision,
    metrics: RenderMetrics,
    *,
    depth_m: NDArray[np.float32] | None = None,
    min_depth_m: float = 0.15,
    max_depth_m: float = 1.2,
    depth_alpha: float = DEFAULT_DEPTH_ALPHA,
) -> OverlayResult:
    image = np.asarray(rgb, dtype=np.uint8).copy()
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("rgb must have shape (height, width, 3)")
    labels: set[str] = set()
    if depth_m is not None:
        image, valid_depth = blend_registered_depth(
            image,
            depth_m,
            min_depth_m=min_depth_m,
            max_depth_m=max_depth_m,
            alpha=depth_alpha,
        )
        if np.any(valid_depth):
            contours, _ = cv2.findContours(
                valid_depth.astype(np.uint8),
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            cv2.drawContours(image, contours, -1, (80, 220, 255), 2)
            labels.add("DEPTH ROI")
    selected_center: tuple[int, int] | None = None
    for index, track in enumerate(decision.tracks):
        candidate = track.candidate
        blockers = list(track.blockers)
        if track.state != "confirmed":
            blockers.insert(0, f"track_{track.state}")
        if not track.depth_supported and "depth_insufficient" not in blockers:
            blockers.append("depth_insufficient")
        blocked = bool(blockers)
        color = _BLOCKED_COLOR if blocked else _ACTIONABLE_COLOR
        if track.stable_id is None:
            color = _COLORS[index % len(_COLORS)]
        mask = candidate.mask
        if mask.shape != image.shape[:2]:
            continue
        tint = np.zeros_like(image)
        tint[mask] = color
        image = cv2.addWeighted(image, 1.0, tint, _MASK_ALPHA, 0.0)
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        is_selected = (
            decision.selected_stable_id is not None
            and track.stable_id == decision.selected_stable_id
        )
        thickness = 4 if is_selected else 2
        cv2.drawContours(image, contours, -1, color, thickness)
        x0, y0, x1, y1 = (int(round(value)) for value in candidate.bbox_xyxy)
        cv2.rectangle(image, (x0, y0), (x1, y1), color, 1)
        center = tuple(int(round(v)) for v in track.centroid_xy)
        stable_label = "?" if track.stable_id is None else str(track.stable_id)
        label = stable_label
        if blocked:
            label = f"{stable_label} BLOCKED {blockers[0]}"
        labels.add(label)
        cv2.circle(image, center, 7 if is_selected else 4, color, -1)
        cv2.putText(
            image,
            label,
            (center[0] + 6, center[1] - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color,
            2,
        )
        if is_selected:
            selected_center = center
            cv2.putText(
                image,
                "SELECTED",
                (center[0] - 35, center[1] + 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

    if selected_center is not None and decision.pose is not None:
        axis_end = (
            selected_center[0] + int(35 * decision.pose.axis[0]),
            selected_center[1] + int(35 * decision.pose.axis[1]),
        )
        approach_end = (
            selected_center[0] + int(35 * decision.pose.approach[0]),
            selected_center[1] + int(35 * decision.pose.approach[1]),
        )
        cv2.arrowedLine(image, selected_center, axis_end, (255, 255, 0), 2)
        cv2.arrowedLine(image, selected_center, approach_end, (255, 0, 255), 2)

    request_label = (
        "NO TARGET SELECTED"
        if decision.selected_stable_id is None
        else f"SELECT {decision.selected_stable_id}"
    )
    labels.add(request_label)
    if decision.status == "ready":
        status_label = f"READY {decision.stable_hits}/{decision.window_size}"
    else:
        reason = decision.reasons[0] if decision.reasons else decision.status
        status_label = f"BLOCKED {reason}"
    labels.update(
        {
            status_label,
            "robot_control_enabled=false",
            "hardware_validation_pending",
            f"FPS {metrics.fps:.1f}",
            f"LATENCY {metrics.latency_ms:.1f} ms",
        }
    )
    if decision.pose is not None:
        labels.add(f"DEPTH {decision.pose.depth_valid_ratio:.0%}")
    depth = "--" if decision.pose is None else (
        f"{decision.pose.point_m[2]:.3f} m {decision.pose.depth_valid_ratio:.0%}"
    )
    panel_lines_list = [
        f"{request_label} | {status_label}",
        f"DEPTH {depth} | FPS {metrics.fps:.1f} | {metrics.latency_ms:.1f} ms",
    ]
    if metrics.dino_ms is not None and metrics.sam_ms is not None:
        panel_lines_list.append(
            f"DINO {metrics.dino_ms:.1f} ms | SAM2 {metrics.sam_ms:.1f} ms"
        )
    panel_lines_list.extend((
        "robot_control_enabled=false",
        "hardware_validation_pending",
    ))
    panel_lines = tuple(panel_lines_list)
    panel_height = min(image.shape[0], 4 + 14 * len(panel_lines))
    dark = image.copy()
    cv2.rectangle(dark, (0, 0), (image.shape[1] - 1, panel_height - 1), (0, 0, 0), -1)
    image = cv2.addWeighted(image, 0.35, dark, 0.65, 0.0)
    font_scale = 0.30 if image.shape[1] < 400 else 0.42
    for row, label in enumerate(panel_lines):
        cv2.putText(image, label, (5, 12 + row * 14), cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale, (245, 245, 245), 1, cv2.LINE_AA)
    if "DEPTH ROI" in labels:
        image = add_depth_legend(
            image,
            min_depth_m=min_depth_m,
            max_depth_m=max_depth_m,
        )
        labels.add("DEPTH LEGEND")
    return OverlayResult(
        image=image,
        labels=frozenset(labels),
        panel_lines=panel_lines,
    )


def encode_jpeg(image: NDArray[np.uint8], quality: int = 85) -> bytes:
    if not 1 <= quality <= 100:
        raise ValueError("JPEG quality must be in [1, 100]")
    ok, encoded = cv2.imencode(
        ".jpg", np.asarray(image, dtype=np.uint8)[..., ::-1],
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return encoded.tobytes()


__all__ = ["OverlayResult", "RenderMetrics", "encode_jpeg", "render_overlay"]
