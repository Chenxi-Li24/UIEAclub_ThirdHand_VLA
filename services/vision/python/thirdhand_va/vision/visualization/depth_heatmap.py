"""Render and blend registered metric depth independently of overlays."""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray


DEFAULT_DEPTH_ALPHA = 0.50


def blend_registered_depth(
    rgb: NDArray[np.uint8],
    depth_m: NDArray[np.float32],
    *,
    min_depth_m: float,
    max_depth_m: float,
    alpha: float = DEFAULT_DEPTH_ALPHA,
) -> tuple[NDArray[np.uint8], NDArray[np.bool_]]:
    """Blend metric depth into RGB only where registered depth is valid."""
    image = np.asarray(rgb, dtype=np.uint8)
    depth = np.asarray(depth_m, dtype=np.float32)
    if depth.shape != image.shape[:2]:
        raise ValueError("registered depth must match the RGB image")
    if not 0.0 <= alpha <= 0.65:
        raise ValueError("depth alpha must be within [0, 0.65]")
    valid = np.isfinite(depth) & (depth >= min_depth_m) & (depth <= max_depth_m)
    if not np.any(valid) or alpha == 0.0:
        return image.copy(), valid
    heatmap = render_depth_heatmap(
        depth, min_depth_m=min_depth_m, max_depth_m=max_depth_m
    )
    blended = cv2.addWeighted(image, 1.0 - alpha, heatmap, alpha, 0.0)
    fused = image.copy()
    fused[valid] = blended[valid]
    return fused, valid


def add_depth_legend(
    rgb: NDArray[np.uint8],
    *,
    min_depth_m: float,
    max_depth_m: float,
) -> NDArray[np.uint8]:
    """Add a compact Turbo near/far scale without changing image dimensions."""
    image = np.asarray(rgb, dtype=np.uint8).copy()
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("rgb must have shape (height, width, 3)")
    if not 0 < min_depth_m < max_depth_m:
        raise ValueError("depth limits must satisfy 0 < min < max")
    if image.shape[0] < 40 or image.shape[1] < 90:
        return image

    legend_width = min(180, max(80, image.shape[1] // 3))
    legend_height = 32
    ramp = np.linspace(
        min_depth_m,
        max_depth_m,
        legend_width,
        dtype=np.float32,
    )[None, :]
    colors = render_depth_heatmap(
        ramp,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
    )
    legend = np.zeros((legend_height, legend_width, 3), dtype=np.uint8)
    legend[:10] = np.repeat(colors, 10, axis=0)
    if legend_width >= 140:
        near = f"NEAR {min_depth_m:.2f}m"
        far = f"FAR {max_depth_m:.2f}m"
    else:
        near = f"N {min_depth_m:.2f}"
        far = f"F {max_depth_m:.2f}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.30
    cv2.putText(
        legend,
        near,
        (1, 27),
        font,
        font_scale,
        (245, 245, 245),
        1,
        cv2.LINE_AA,
    )
    far_width = cv2.getTextSize(far, font, font_scale, 1)[0][0]
    cv2.putText(
        legend,
        far,
        (max(1, legend_width - far_width - 1), 27),
        font,
        font_scale,
        (245, 245, 245),
        1,
        cv2.LINE_AA,
    )
    x0 = image.shape[1] - legend_width - 5
    y0 = 4
    image[y0 : y0 + legend_height, x0 : x0 + legend_width] = legend
    return image


def render_depth_heatmap(
    depth_m: NDArray[np.float32], *, min_depth_m: float, max_depth_m: float
) -> NDArray[np.uint8]:
    """Render registered metric depth as RGB TURBO; invalid pixels stay black."""
    depth = np.asarray(depth_m, dtype=np.float32)
    if depth.ndim != 2 or not 0 < min_depth_m < max_depth_m:
        raise ValueError("depth must be 2-D and limits must satisfy 0 < min < max")
    valid = np.isfinite(depth) & (depth >= min_depth_m) & (depth <= max_depth_m)
    normalized = np.zeros(depth.shape, dtype=np.uint8)
    normalized[valid] = np.clip(
        (max_depth_m - depth[valid]) / (max_depth_m - min_depth_m) * 255,
        0,
        255,
    ).astype(np.uint8)
    bgr = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
    bgr[~valid] = 0
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


__all__ = [
    "DEFAULT_DEPTH_ALPHA",
    "add_depth_legend",
    "blend_registered_depth",
    "render_depth_heatmap",
]
