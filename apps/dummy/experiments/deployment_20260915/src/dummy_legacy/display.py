from __future__ import annotations

import cv2


def prepare_color_frame(frame, *, mirror=False):
    """Return a BGR display frame without discarding camera colour."""

    if frame is None:
        return None
    prepared = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR) if len(frame.shape) == 2 else frame.copy()
    return cv2.flip(prepared, 1) if mirror else prepared
