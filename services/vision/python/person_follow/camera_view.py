from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np


class VirtualPinholeView:
    def __init__(self, *, width, height, fx, fy, cx, cy, xi, alpha, source_width=None, source_height=None):
        values = [width, height, fx, fy, cx, cy, xi, alpha]
        if not all(np.isfinite(values)) or width <= 0 or height <= 0 or fx <= 0 or fy <= 0:
            raise ValueError("valid calibrated SEUCM parameters are required")
        self.width, self.height = int(width), int(height)
        self.fx, self.fy, self.cx, self.cy = map(float, (fx, fy, cx, cy))
        self.xi, self.alpha = float(xi), float(alpha)
        self.source_width = int(source_width or width)
        self.source_height = int(source_height or height)
        payload = dict(width=self.width, height=self.height, fx=self.fx, fy=self.fy, cx=self.cx, cy=self.cy, xi=self.xi, alpha=self.alpha, source_width=self.source_width, source_height=self.source_height)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.calibration_hash = hashlib.sha256(encoded).hexdigest()
        self.camera_view_id = f"seucm-pinhole-{self.calibration_hash[:12]}"
        self._map_x, self._map_y = self._build_map()

    def _build_map(self):
        u, v = np.meshgrid(np.arange(self.width, dtype=np.float32), np.arange(self.height, dtype=np.float32))
        x = (u - self.cx) / self.fx
        y = (v - self.cy) / self.fy
        z = np.ones_like(x)
        norm = np.sqrt(x * x + y * y + z * z)
        denom = self.alpha * norm + (1.0 - self.alpha) * (self.xi * norm + z)
        denom = np.where(np.abs(denom) < 1e-6, 1e-6, denom)
        sx = self.fx * x / denom + self.source_width / 2.0
        sy = self.fy * y / denom + self.source_height / 2.0
        return sx.astype(np.float32), sy.astype(np.float32)

    def rectify(self, frame):
        if frame is None or frame.ndim not in (2, 3):
            raise ValueError("a valid image frame is required")
        return cv2.remap(frame, self._map_x, self._map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
