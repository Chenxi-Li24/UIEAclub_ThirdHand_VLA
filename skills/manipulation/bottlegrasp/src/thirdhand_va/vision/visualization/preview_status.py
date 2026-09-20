"""Pure rendering helpers for preview fallback and offline states."""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray


def _validated_rgb(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    image = np.asarray(rgb)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("rgb must be a uint8 RGB image")
    return image


def render_preview_banner(
    rgb: NDArray[np.uint8],
    *,
    title: str,
    detail: str,
) -> NDArray[np.uint8]:
    """Return a copy with a visible warning panel at the top."""

    image = _validated_rgb(rgb)
    rendered = image.copy()
    panel_height = min(rendered.shape[0], 60)
    panel = np.full(
        (panel_height, rendered.shape[1], 3),
        (18, 18, 22),
        dtype=np.uint8,
    )
    rendered[:panel_height] = cv2.addWeighted(
        rendered[:panel_height], 0.25, panel, 0.75, 0.0
    )
    scale = 0.42 if rendered.shape[1] >= 400 else 0.32
    cv2.putText(
        rendered,
        str(title),
        (8, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (255, 76, 76),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        rendered,
        str(detail),
        (8, 47),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (235, 235, 235),
        1,
        cv2.LINE_AA,
    )
    return rendered


def render_offline_frame(
    width: int,
    height: int,
    detail: str,
) -> NDArray[np.uint8]:
    """Create a stable visible frame while neither upstream stream is usable."""

    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width < 64
        or height < 64
    ):
        raise ValueError("width and height must be integers of at least 64 pixels")
    image = np.full((height, width, 3), (22, 26, 32), dtype=np.uint8)
    spacing = max(32, min(width, height) // 6)
    for offset in range(-height, width, spacing):
        cv2.line(
            image,
            (offset, height - 1),
            (offset + height, 0),
            (31, 37, 45),
            1,
            cv2.LINE_AA,
        )
    return render_preview_banner(
        image,
        title="CAMERA PREVIEW OFFLINE",
        detail=detail,
    )


__all__ = ["render_offline_frame", "render_preview_banner"]
