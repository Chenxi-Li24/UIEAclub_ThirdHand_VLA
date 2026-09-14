"""Pure composition for the native RGB/algorithm/depth monitor."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from .depth_heatmap import add_depth_legend


DEFAULT_MONITOR_DEPTH_ALPHA = 0.35


@dataclass(frozen=True, slots=True)
class MonitorFrame:
    image_rgb: NDArray[np.uint8]
    frame_id: int
    valid_pixels: int
    valid_ratio: float
    depth_roi_xyxy: tuple[int, int, int, int] | None = None


def compose_monitor_frame(
    algorithm_rgb: NDArray[np.uint8],
    depth_heatmap_rgb: NDArray[np.uint8],
    *,
    frame_id: int,
    alpha: float = DEFAULT_MONITOR_DEPTH_ALPHA,
    valid_threshold: int = 12,
    min_depth_m: float = 0.15,
    max_depth_m: float = 1.20,
    depth_roi_xyxy: tuple[int, int, int, int] | None = None,
) -> MonitorFrame:
    """Strengthen a registered colored depth stream over one algorithm frame."""
    algorithm = np.asarray(algorithm_rgb)
    depth = np.asarray(depth_heatmap_rgb)
    if algorithm.dtype != np.uint8 or algorithm.ndim != 3 or algorithm.shape[2] != 3:
        raise ValueError("algorithm_rgb must be a uint8 RGB image")
    if depth.dtype != np.uint8 or depth.ndim != 3 or depth.shape[2] != 3:
        raise ValueError("depth_heatmap_rgb must be a uint8 RGB image")
    if depth.shape != algorithm.shape:
        raise ValueError("registered depth heatmap must match the algorithm image")
    if frame_id < 0:
        raise ValueError("frame_id must be non-negative")
    if not 0.0 <= float(alpha) <= 0.65:
        raise ValueError("alpha must be within [0, 0.65]")
    if isinstance(valid_threshold, bool) or not 0 <= int(valid_threshold) <= 254:
        raise ValueError("valid_threshold must be within [0, 254]")
    if depth_roi_xyxy is not None:
        if (
            len(depth_roi_xyxy) != 4
            or any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in depth_roi_xyxy
            )
        ):
            raise ValueError("depth_roi_xyxy must contain four integer coordinates")
        x0, y0, x1, y1 = depth_roi_xyxy
        if not (0 <= x0 < x1 < algorithm.shape[1] and 0 <= y0 < y1 < algorithm.shape[0]):
            raise ValueError("depth_roi_xyxy must fit within the registered image")

    valid = np.max(depth, axis=2) > int(valid_threshold)
    fused = algorithm.copy()
    if np.any(valid):
        if alpha > 0:
            blended = cv2.addWeighted(
                algorithm,
                1.0 - float(alpha),
                depth,
                float(alpha),
                0.0,
            )
            fused[valid] = blended[valid]
            fused = add_depth_legend(
                fused,
                min_depth_m=min_depth_m,
                max_depth_m=max_depth_m,
            )
    if depth_roi_xyxy is not None:
        x0, y0, x1, y1 = depth_roi_xyxy
        cv2.rectangle(fused, (x0, y0), (x1, y1), (255, 255, 0), 2)
        cv2.putText(
            fused,
            "DEPTH HARDWARE FOV",
            (x0, max(12, y0 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (255, 255, 0),
            1,
            cv2.LINE_AA,
        )

    valid_pixels = int(np.count_nonzero(valid))
    valid_ratio = valid_pixels / valid.size
    status = f"DEPTH SYNC frame={frame_id} | valid={valid_ratio:.1%}"
    baseline = fused.shape[0] - 8
    cv2.putText(
        fused,
        status,
        (6, baseline),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42 if fused.shape[1] >= 400 else 0.32,
        (245, 245, 245),
        1,
        cv2.LINE_AA,
    )
    return MonitorFrame(
        image_rgb=fused,
        frame_id=frame_id,
        valid_pixels=valid_pixels,
        valid_ratio=valid_ratio,
        depth_roi_xyxy=depth_roi_xyxy,
    )


def render_monitor_notice(
    algorithm_rgb: NDArray[np.uint8],
    *,
    frame_id: int,
    detail: str,
) -> NDArray[np.uint8]:
    """Keep the algorithm image visible while marking unavailable depth."""
    image = np.asarray(algorithm_rgb)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("algorithm_rgb must be a uint8 RGB image")
    if frame_id < 0:
        raise ValueError("frame_id must be non-negative")
    rendered = image.copy()
    panel_height = min(30, rendered.shape[0])
    y0 = rendered.shape[0] - panel_height
    dark = rendered.copy()
    cv2.rectangle(
        dark,
        (0, y0),
        (rendered.shape[1] - 1, rendered.shape[0] - 1),
        (90, 20, 20),
        -1,
    )
    rendered = cv2.addWeighted(rendered, 0.35, dark, 0.65, 0.0)
    cv2.putText(
        rendered,
        f"{detail} | algorithm frame={frame_id}",
        (6, rendered.shape[0] - 9),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42 if rendered.shape[1] >= 400 else 0.32,
        (255, 245, 245),
        1,
        cv2.LINE_AA,
    )
    return rendered


__all__ = [
    "DEFAULT_MONITOR_DEPTH_ALPHA",
    "MonitorFrame",
    "compose_monitor_frame",
    "render_monitor_notice",
]
