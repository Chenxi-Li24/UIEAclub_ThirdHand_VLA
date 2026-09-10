"""Registered hardware depth coverage in RGB image coordinates."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class RegisteredDepthCoverage:
    """One camera's calibrated depth field of view at a reference size."""

    camera_serial: str
    reference_size: tuple[int, int]
    roi_xyxy: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        if not self.camera_serial.strip():
            raise ValueError("camera_serial must not be empty")
        if (
            len(self.reference_size) != 2
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in self.reference_size
            )
        ):
            raise ValueError("reference_size must contain two positive integers")
        if (
            len(self.roi_xyxy) != 4
            or any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in self.roi_xyxy
            )
        ):
            raise ValueError("roi_xyxy must contain four integer coordinates")
        width, height = self.reference_size
        x0, y0, x1, y1 = self.roi_xyxy
        if not (0 <= x0 < x1 < width and 0 <= y0 < y1 < height):
            raise ValueError("roi_xyxy must fit within reference_size")

    def roi_for_size(self, width: int, height: int) -> tuple[int, int, int, int]:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (width, height)
        ):
            raise ValueError("target size must contain two positive integers")
        reference_width, reference_height = self.reference_size
        x0, y0, x1, y1 = self.roi_xyxy
        scale_x = int(width) / reference_width
        scale_y = int(height) / reference_height
        return (
            math.floor(x0 * scale_x),
            math.floor(y0 * scale_y),
            math.ceil((x1 + 1) * scale_x) - 1,
            math.ceil((y1 + 1) * scale_y) - 1,
        )


__all__ = ["RegisteredDepthCoverage"]
