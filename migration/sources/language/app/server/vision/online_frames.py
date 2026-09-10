"""Logical online camera roles and immutable latest-frame pairing contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .types import FrameStamp, InvalidDataError


@dataclass(frozen=True)
class CameraRoleMap:
    canonical_rgb_source: str
    metric_depth_source: str
    debug_rgb_source: Optional[str]
    fusion_mode: str

    def __post_init__(self) -> None:
        sources = (self.canonical_rgb_source, self.metric_depth_source)
        if any(not isinstance(value, str) or not value.strip() for value in sources):
            raise InvalidDataError("canonical RGB and metric depth sources are required")
        if self.canonical_rgb_source == self.metric_depth_source:
            raise InvalidDataError("canonical RGB and metric depth streams must be distinct")
        if self.debug_rgb_source is not None and (
            not isinstance(self.debug_rgb_source, str) or not self.debug_rgb_source.strip()
        ):
            raise InvalidDataError("debug RGB source must be a non-empty string or None")
        if self.fusion_mode not in {"cross_camera", "native_aligned"}:
            raise InvalidDataError("fusion mode must be cross_camera or native_aligned")


@dataclass(frozen=True)
class RgbFrame:
    stamp: FrameStamp
    image_rgb: np.ndarray

    def __post_init__(self) -> None:
        image = np.array(self.image_rgb, copy=True)
        if (
            image.dtype != np.uint8
            or image.ndim != 3
            or image.shape[2] != 3
            or image.shape[0] < 1
            or image.shape[1] < 1
        ):
            raise InvalidDataError("RGB image must be a non-empty uint8 HxWx3 array")
        image.setflags(write=False)
        object.__setattr__(self, "image_rgb", image)


@dataclass(frozen=True)
class DepthFrame:
    stamp: FrameStamp
    depth_z_m: np.ndarray

    def __post_init__(self) -> None:
        depth = np.array(self.depth_z_m, dtype=float, copy=True)
        finite = np.isfinite(depth)
        if depth.ndim != 2 or depth.shape[0] < 1 or depth.shape[1] < 1:
            raise InvalidDataError("depth image must be a non-empty 2D array")
        if np.isinf(depth).any() or np.any(depth[finite] < 0.0):
            raise InvalidDataError("depth image may contain non-negative values or NaN only")
        depth.setflags(write=False)
        object.__setattr__(self, "depth_z_m", depth)


@dataclass(frozen=True)
class FramePair:
    rgb: RgbFrame
    depth: Optional[DepthFrame]
    fusion_monotonic_ns: int
    frame_skew_ns: Optional[int]
    reasons: tuple[str, ...]
    debug_rgb: Optional[RgbFrame] = None


class LatestFramePairer:
    def __init__(
        self,
        roles: CameraRoleMap,
        max_frame_skew_ns: int,
        max_frame_age_ns: int,
    ) -> None:
        if not isinstance(roles, CameraRoleMap):
            raise InvalidDataError("camera role map is required")
        if any(
            not isinstance(value, int) or value < 0
            for value in (max_frame_skew_ns, max_frame_age_ns)
        ):
            raise InvalidDataError("frame timing limits must be non-negative integers")
        self.roles = roles
        self.max_frame_skew_ns = max_frame_skew_ns
        self.max_frame_age_ns = max_frame_age_ns
        self._last_rgb_frame_id: Optional[int] = None
        self._last_rgb_monotonic_ns: Optional[int] = None
        self._last_depth_frame_id: Optional[int] = None
        self._last_depth_monotonic_ns: Optional[int] = None

    def pair(
        self,
        rgb: RgbFrame,
        depth: Optional[DepthFrame],
        now_ns: int,
        *,
        debug_rgb: Optional[RgbFrame] = None,
    ) -> FramePair:
        if not isinstance(rgb, RgbFrame):
            raise InvalidDataError("RGB frame is required")
        if rgb.stamp.source != self.roles.canonical_rgb_source:
            raise InvalidDataError("frame does not use the configured canonical RGB source")
        if depth is not None:
            if not isinstance(depth, DepthFrame):
                raise InvalidDataError("depth must be a DepthFrame or None")
            if depth.stamp.source != self.roles.metric_depth_source:
                raise InvalidDataError("frame does not use the configured metric depth source")
        if debug_rgb is not None:
            if not isinstance(debug_rgb, RgbFrame):
                raise InvalidDataError("debug RGB must be an RgbFrame or None")
            if (
                self.roles.debug_rgb_source is None
                or debug_rgb.stamp.source != self.roles.debug_rgb_source
            ):
                raise InvalidDataError("frame does not use the configured debug RGB source")
            if depth is None or (
                debug_rgb.stamp.frame_id != depth.stamp.frame_id
                or debug_rgb.stamp.monotonic_ns != depth.stamp.monotonic_ns
            ):
                raise InvalidDataError("debug RGB and metric depth must be synchronized")
            if debug_rgb.image_rgb.shape[:2] != depth.depth_z_m.shape:
                raise InvalidDataError("debug RGB and metric depth dimensions must match")
        if self._last_rgb_frame_id is not None and (
            rgb.stamp.frame_id <= self._last_rgb_frame_id
            or rgb.stamp.monotonic_ns <= self._last_rgb_monotonic_ns
        ):
            raise InvalidDataError("RGB frame provenance must strictly advance")
        if depth is not None and self._last_depth_frame_id is not None and (
            depth.stamp.frame_id <= self._last_depth_frame_id
            or depth.stamp.monotonic_ns <= self._last_depth_monotonic_ns
        ):
            raise InvalidDataError("depth frame provenance must strictly advance")
        if not isinstance(now_ns, int) or now_ns < 0:
            raise InvalidDataError("now_ns must be a non-negative integer")

        fusion_ns = rgb.stamp.monotonic_ns
        skew_ns: Optional[int] = None
        reasons: list[str] = []
        if depth is None:
            reasons.append("depth_unavailable")
        else:
            fusion_ns = max(fusion_ns, depth.stamp.monotonic_ns)
            skew_ns = abs(rgb.stamp.monotonic_ns - depth.stamp.monotonic_ns)
            if skew_ns > self.max_frame_skew_ns:
                reasons.append("frame_skew_exceeded")
        if now_ns < fusion_ns:
            raise InvalidDataError("camera frame timestamp cannot be in the future")
        if now_ns - fusion_ns > self.max_frame_age_ns:
            reasons.append("camera_frames_stale")
        self._last_rgb_frame_id = rgb.stamp.frame_id
        self._last_rgb_monotonic_ns = rgb.stamp.monotonic_ns
        if depth is not None:
            self._last_depth_frame_id = depth.stamp.frame_id
            self._last_depth_monotonic_ns = depth.stamp.monotonic_ns
        return FramePair(
            rgb=rgb,
            depth=depth,
            fusion_monotonic_ns=fusion_ns,
            frame_skew_ns=skew_ns,
            reasons=tuple(reasons),
            debug_rgb=debug_rgb,
        )
