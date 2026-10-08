from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class RgbdTarget:
    found: bool
    u: float = 0.0
    v: float = 0.0
    w: int = 0
    h: int = 0
    score: float = 0.0
    kind: str = "none"
    ts: float = 0.0
    xyz_m: list[float] | None = None
    depth_valid: bool = False
    depth_valid_ratio: float = 0.0
    valid_depth_points: int = 0
    depth_m: float | None = None
    stable_id: int | None = None
    frame_id: int | None = None
    observed_at_ms: int | None = None
    monotonic_ns: int | None = None
    base_xyz_m: list[float] | None = None
    base_pose_status: str | None = None


class RgbdTargetBuilder:
    """Normalize 3100 RGB-D observations into the DUM-E follow target shape."""

    def __init__(self, config: dict[str, Any], *, now_ms=None):
        options = config.get("rgbd_target", {})
        vision = config.get("vision", {})
        self.frame_w = int(vision.get("frame_w", 640))
        self.frame_h = int(vision.get("frame_h", 480))
        self.max_observation_age_ms = int(float(options.get("max_observation_age_s", 0.30)) * 1000)
        self.min_depth_ratio = float(options.get("min_depth_ratio", 0.08))
        self.min_depth_points = int(options.get("min_depth_points", 150))
        self.prefer_labels = [str(item).lower() for item in options.get("prefer_labels", ["person", "face", "human"])]
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))

    def from_observation(self, observation: dict[str, Any] | None) -> RgbdTarget:
        if not isinstance(observation, dict):
            return RgbdTarget(False, w=self.frame_w, h=self.frame_h, kind="rgbd_unavailable", ts=time.time())
        observed_at = _optional_int(observation.get("observedAtMs"))
        if observed_at is not None and self._now_ms() - observed_at > self.max_observation_age_ms:
            return self._missing(observation, "rgbd_stale")
        target = self._choose_target(observation)
        if not isinstance(target, dict):
            return self._missing(observation, "rgbd_lost")
        centroid = _centroid(target)
        if centroid is None:
            return self._missing(observation, "rgbd_no_centroid")
        box = _bbox_size(target)
        score = _finite_float(target.get("score"), 0.0)
        depth_ok = self._depth_is_valid(target)
        xyz = _finite_vector(target.get("camera_xyz_m"), 3) if depth_ok else None
        label = str(target.get("label") or "target").lower()
        kind_prefix = "person" if label in {"person", "face", "human"} else label
        return RgbdTarget(
            True,
            u=centroid[0],
            v=centroid[1],
            w=self.frame_w,
            h=self.frame_h,
            score=score,
            kind=f"{kind_prefix}_depth" if xyz is not None else f"{kind_prefix}_2d",
            ts=time.time(),
            xyz_m=xyz,
            depth_valid=xyz is not None,
            depth_valid_ratio=_finite_float(target.get("depth_valid_ratio"), 0.0),
            valid_depth_points=int(_finite_float(target.get("valid_depth_points"), 0.0)),
            depth_m=_finite_float_or_none(target.get("depth_m")),
            stable_id=_optional_int(target.get("stable_id", target.get("stableId"))),
            frame_id=_optional_int(observation.get("frameId")),
            observed_at_ms=observed_at,
            monotonic_ns=_optional_int(observation.get("monotonicNs")),
            base_xyz_m=_finite_vector(target.get("base_xyz_m"), 3),
            base_pose_status=None if target.get("base_pose_status") is None else str(target.get("base_pose_status")),
        )

    def _choose_target(self, observation: dict[str, Any]) -> dict[str, Any] | None:
        selected = observation.get("target")
        if isinstance(selected, dict):
            return selected
        targets = [item for item in observation.get("targets", []) if isinstance(item, dict)]
        if not targets:
            return None

        def rank(item):
            label = str(item.get("label") or "").lower()
            label_bonus = 1.0 if label in self.prefer_labels else 0.0
            score = _finite_float(item.get("score"), 0.0)
            depth_bonus = 0.2 if self._depth_is_valid(item) else 0.0
            return label_bonus + depth_bonus + score

        return max(targets, key=rank)

    def _depth_is_valid(self, target: dict[str, Any]) -> bool:
        if target.get("depth_valid") is not True:
            return False
        ratio = _finite_float(target.get("depth_valid_ratio"), 0.0)
        points = int(_finite_float(target.get("valid_depth_points"), 0.0))
        return ratio >= self.min_depth_ratio and points >= self.min_depth_points and _finite_vector(target.get("camera_xyz_m"), 3) is not None

    def _missing(self, observation: dict[str, Any], kind: str) -> RgbdTarget:
        return RgbdTarget(
            False,
            w=self.frame_w,
            h=self.frame_h,
            kind=kind,
            ts=time.time(),
            frame_id=_optional_int(observation.get("frameId")),
            observed_at_ms=_optional_int(observation.get("observedAtMs")),
            monotonic_ns=_optional_int(observation.get("monotonicNs")),
        )


def _centroid(target: dict[str, Any]) -> tuple[float, float] | None:
    value = target.get("centroid_xy")
    vector = _finite_vector(value, 2)
    if vector is not None:
        return vector[0], vector[1]
    bbox = target.get("bbox_xyxy")
    if isinstance(bbox, list) and len(bbox) == 4:
        values = [_finite_float_or_none(item) for item in bbox]
        if all(item is not None for item in values):
            x1, y1, x2, y2 = values
            return (x1 + x2) / 2.0, (y1 + y2) / 2.0
    return None


def _bbox_size(target: dict[str, Any]) -> tuple[float, float]:
    bbox = target.get("bbox_xyxy")
    if isinstance(bbox, list) and len(bbox) == 4:
        values = [_finite_float_or_none(item) for item in bbox]
        if all(item is not None for item in values):
            x1, y1, x2, y2 = values
            return max(1.0, x2 - x1), max(1.0, y2 - y1)
    return 1.0, 1.0


def _finite_vector(value: Any, length: int) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return None
    out = []
    for item in value:
        number = _finite_float_or_none(item)
        if number is None:
            return None
        out.append(number)
    return out


def _finite_float(value: Any, default: float) -> float:
    number = _finite_float_or_none(value)
    return default if number is None else number


def _finite_float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _optional_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number
