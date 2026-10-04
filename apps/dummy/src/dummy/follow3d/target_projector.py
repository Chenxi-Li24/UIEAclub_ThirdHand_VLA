from __future__ import annotations

import math


class Virtual3DTargetProjector:
    """Project a 2D lock point into a conservative virtual 3D gaze target."""

    def __init__(self, config):
        options = config.get("virtual_3d_target", {})
        vision = config.get("vision", {})
        self.enabled = bool(options.get("enabled", True))
        self.default_depth_m = float(options.get("default_depth_m", 1.5))
        self.focal_px = float(options.get("focal_px", 520.0))
        self.max_gaze_depth_m = float(options.get("max_gaze_depth_m", self.default_depth_m))
        self.max_x_m = float(options.get("max_x_m", 0.65))
        self.max_y_m = float(options.get("max_y_m", 0.45))
        self.smoothing_alpha = float(options.get("smoothing_alpha", 0.35))
        self.frame_w = int(vision.get("frame_w", 640))
        self.frame_h = int(vision.get("frame_h", 480))
        self._last_xyz = None

    def reset(self):
        self._last_xyz = None

    def ensure_xyz(self, target, *, depth_hint_m=None):
        if not self.enabled or not getattr(target, "found", False):
            return False
        xyz = getattr(target, "xyz_m", None)
        if _finite_xyz(xyz):
            return False
        depth = self._depth(depth_hint_m)
        width = float(getattr(target, "w", 0) or self.frame_w)
        height = float(getattr(target, "h", 0) or self.frame_h)
        u = float(getattr(target, "u", width / 2.0))
        v = float(getattr(target, "v", height / 2.0))
        x = (u - width / 2.0) / max(1.0, self.focal_px) * depth
        y = (v - height / 2.0) / max(1.0, self.focal_px) * depth
        xyz = [_clamp(x, -self.max_x_m, self.max_x_m), _clamp(y, -self.max_y_m, self.max_y_m), depth]
        if self._last_xyz is not None:
            alpha = _clamp(self.smoothing_alpha, 0.0, 1.0)
            xyz = [self._last_xyz[i] + alpha * (xyz[i] - self._last_xyz[i]) for i in range(3)]
        self._last_xyz = list(xyz)
        target.xyz_m = xyz
        target.depth_m = depth
        target.estimated_depth_m = depth
        target.depth_valid = False
        kind = str(getattr(target, 'kind', 'target'))
        target.kind = kind if kind.endswith("_virtual3d") else f"{kind}_virtual3d"
        return True

    def _depth(self, value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = self.default_depth_m
        if not math.isfinite(number) or number <= 0:
            number = self.default_depth_m
        if self.max_gaze_depth_m > 0:
            number = min(number, self.max_gaze_depth_m)
        return number


def _finite_xyz(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return False
    try:
        return all(math.isfinite(float(item)) for item in value)
    except (TypeError, ValueError):
        return False


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))
