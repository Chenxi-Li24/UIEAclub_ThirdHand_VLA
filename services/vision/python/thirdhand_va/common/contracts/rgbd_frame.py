"""Immutable, registered RGB-D frame contract."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ._validation import readonly_array


@dataclass(frozen=True, slots=True)
class RgbdFrame:
    sequence: int
    monotonic_ns: int
    camera_serial: str
    rgb: NDArray[np.uint8]
    depth_m: NDArray[np.float32]
    xyz_camera_m: NDArray[np.float32]

    def __post_init__(self) -> None:
        rgb = readonly_array(self.rgb, dtype=np.uint8)
        depth = readonly_array(self.depth_m, dtype=np.float32)
        xyz = readonly_array(self.xyz_camera_m, dtype=np.float32)
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("rgb must have shape (height, width, 3)")
        if depth.shape != rgb.shape[:2] or xyz.shape != (*rgb.shape[:2], 3):
            raise ValueError("depth and xyz must be aligned to the RGB image")
        if self.sequence < 0 or self.monotonic_ns < 0:
            raise ValueError("frame sequence and timestamp must be non-negative")
        if not self.camera_serial:
            raise ValueError("camera_serial must not be empty")
        object.__setattr__(self, "rgb", rgb)
        object.__setattr__(self, "depth_m", depth)
        object.__setattr__(self, "xyz_camera_m", xyz)


__all__ = ["RgbdFrame"]
