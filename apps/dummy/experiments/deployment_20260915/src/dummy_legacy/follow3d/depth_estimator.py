from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class EstimatedDepth:
    depth_m: float
    source: str
    confidence: float
    metric: bool
    reason: str


class DepthEstimator:
    """Fuse RGB-D depth with monocular person-size depth hints."""

    def __init__(self, config):
        options = config.get("monocular_depth", {})
        virtual = config.get("virtual_3d_target", {})
        self.enabled = bool(options.get("enabled", True))
        self.focal_px = float(options.get("focal_px", virtual.get("focal_px", 520.0)))
        self.body_height_m = float(options.get("assumed_body_height_m", 1.65))
        self.face_height_m = float(options.get("assumed_face_height_m", 0.22))
        self.min_bbox_h_px = float(options.get("min_bbox_h_px", 35.0))
        self.min_depth_m = float(options.get("min_depth_m", 0.45))
        self.max_depth_m = float(options.get("max_depth_m", 2.50))
        self.default_depth_m = float(options.get("default_depth_m", virtual.get("default_depth_m", 1.50)))
        self.smoothing_alpha = float(options.get("smoothing_alpha", 0.30))
        self.rgbd_weight = float(options.get("rgbd_weight", 0.75))
        self.mono_weight = float(options.get("mono_weight", 0.25))
        self.rgbd_confidence = float(options.get("rgbd_confidence", 1.0))
        self.bbox_confidence = float(options.get("bbox_confidence", 0.55))
        self.fallback_confidence = float(options.get("fallback_confidence", 0.15))
        self._last_depth_m: float | None = None

    def reset(self):
        self._last_depth_m = None

    def estimate(self, target, debug=None):
        debug = debug or {}
        rgbd = self._rgbd_depth(target, debug)
        mono = self._mono_depth(target, debug)
        if rgbd is not None:
            if mono is not None and self.mono_weight > 0.0:
                depth = self._weighted_depth(rgbd, mono.depth_m)
                confidence = max(self.rgbd_confidence, min(1.0, (self.rgbd_confidence + mono.confidence) / 2.0))
                return self._finish(depth, "fused", confidence, True, f"rgbd+{mono.reason}")
            return self._finish(rgbd, "rgbd", self.rgbd_confidence, True, "camera_depth")

        if mono is not None:
            return self._finish(mono.depth_m, mono.source, mono.confidence, False, mono.reason)

        return self._finish(self.default_depth_m, "fallback", self.fallback_confidence, False, "default_virtual_depth")

    def _mono_depth(self, target, debug):
        if not self.enabled or not getattr(target, "found", False):
            return None
        bbox = self._bbox(debug)
        if bbox is None:
            return None
        _, _, _, h = bbox
        if h < self.min_bbox_h_px:
            return None
        kind = str(debug.get("lock_candidate", {}).get("kind") or getattr(target, "kind", "person"))
        real_h = self.face_height_m if "face" in kind else self.body_height_m
        depth = self.focal_px * real_h / max(1.0, h)
        depth = _clamp(depth, self.min_depth_m, self.max_depth_m)
        return EstimatedDepth(depth, "mono_bbox", self.bbox_confidence, False, f"{kind}_height")

    def _finish(self, depth_m, source, confidence, metric, reason):
        depth = _clamp(float(depth_m), self.min_depth_m, self.max_depth_m)
        if self._last_depth_m is not None:
            alpha = _clamp(self.smoothing_alpha, 0.0, 1.0)
            depth = self._last_depth_m + alpha * (depth - self._last_depth_m)
        self._last_depth_m = depth
        return EstimatedDepth(depth, source, _clamp(confidence, 0.0, 1.0), metric, reason)

    def _rgbd_depth(self, target, debug):
        if bool(getattr(target, "depth_valid", False)):
            value = getattr(target, "depth_m", None)
            if value is None:
                xyz = getattr(target, "xyz_m", None)
                if isinstance(xyz, (list, tuple)) and len(xyz) == 3:
                    value = xyz[2]
            return _finite_positive(value)
        if bool(debug.get("rgbd_depth_valid")):
            value = _finite_positive(debug.get("rgbd_depth_m"))
            if value is not None:
                return value
            xyz = debug.get("rgbd_xyz_m")
            if isinstance(xyz, (list, tuple)) and len(xyz) == 3:
                return _finite_positive(xyz[2])
        return None

    def _weighted_depth(self, rgbd, mono):
        rgbd_weight = max(0.0, float(self.rgbd_weight))
        mono_weight = max(0.0, float(self.mono_weight))
        total = rgbd_weight + mono_weight
        if total <= 0.0:
            return rgbd
        return (float(rgbd) * rgbd_weight + float(mono) * mono_weight) / total

    def _bbox(self, debug):
        candidate = debug.get("lock_candidate")
        if isinstance(candidate, dict):
            values = (candidate.get("u", 0.0), candidate.get("v", 0.0), candidate.get("w", 0.0), candidate.get("h", 0.0))
            box = _finite_box(values)
            if box is not None:
                return box
        for key in ("person_bbox", "bbox"):
            box = _finite_box(debug.get(key))
            if box is not None:
                return box
        return None


def _finite_positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0.0 else None


def _finite_box(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, w, h = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (x, y, w, h)) or w <= 0.0 or h <= 0.0:
        return None
    return x, y, w, h


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))
