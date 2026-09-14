"""Immutable candidates, poses, ranks, and decisions produced by Vision."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from ._validation import finite_triplet, readonly_array

DecisionStatus = Literal[
    "searching",
    "rejected",
    "uncertain",
    "unstable",
    "ready",
]
TrackState = Literal["tentative", "confirmed", "occluded", "lost", "retired"]


@dataclass(frozen=True, slots=True)
class MaskCandidate:
    detection_id: int
    label: str
    score: float
    bbox_xyxy: tuple[float, float, float, float]
    mask: NDArray[np.bool_]
    authorized: bool
    reasons: tuple[str, ...] = ()
    descriptor: NDArray[np.float32] | None = None

    def __post_init__(self) -> None:
        mask = readonly_array(self.mask, dtype=np.bool_)
        bbox = tuple(float(value) for value in self.bbox_xyxy)
        if mask.ndim != 2:
            raise ValueError("mask must be two-dimensional")
        if len(bbox) != 4 or not np.isfinite(bbox).all():
            raise ValueError("bbox_xyxy must contain four finite values")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be in [0, 1]")
        descriptor = self.descriptor
        if descriptor is not None:
            descriptor = readonly_array(descriptor, dtype=np.float32)
            if descriptor.ndim != 1 or descriptor.size == 0:
                raise ValueError("descriptor must be a non-empty vector")
            if not np.isfinite(descriptor).all():
                raise ValueError("descriptor must contain finite values")
        object.__setattr__(self, "mask", mask)
        object.__setattr__(self, "bbox_xyxy", bbox)
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "descriptor", descriptor)


@dataclass(frozen=True, slots=True)
class TrackedBottle:
    stable_id: int | None
    backend_track_id: int
    state: TrackState
    candidate: MaskCandidate
    centroid_xy: tuple[float, float]
    depth_supported: bool
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.stable_id is not None and not 1 <= self.stable_id <= 5:
            raise ValueError("stable_id must be in [1, 5] when assigned")
        if self.backend_track_id < 0:
            raise ValueError("backend_track_id must be non-negative")
        if self.state not in {
            "tentative", "confirmed", "occluded", "lost", "retired"
        }:
            raise ValueError(f"unsupported track state: {self.state}")
        centroid = tuple(float(value) for value in self.centroid_xy)
        if len(centroid) != 2 or not np.isfinite(centroid).all():
            raise ValueError("centroid_xy must contain two finite values")
        object.__setattr__(self, "centroid_xy", centroid)
        object.__setattr__(self, "depth_supported", self.depth_supported is True)
        object.__setattr__(self, "blockers", tuple(self.blockers))


@dataclass(frozen=True, slots=True)
class GraspPoseCamera:
    point_m: tuple[float, float, float]
    axis: tuple[float, float, float]
    approach: tuple[float, float, float]
    width_m: float
    position_std_m: tuple[float, float, float]
    valid_points: int
    depth_valid_ratio: float
    frame: str = "xvisio_color"
    height_m: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "point_m", finite_triplet(self.point_m, "point_m"))
        object.__setattr__(self, "axis", finite_triplet(self.axis, "axis"))
        object.__setattr__(self, "approach", finite_triplet(self.approach, "approach"))
        object.__setattr__(
            self,
            "position_std_m",
            finite_triplet(self.position_std_m, "position_std_m"),
        )
        if self.width_m <= 0 or self.valid_points <= 0:
            raise ValueError("width_m and valid_points must be positive")
        if self.height_m is not None and self.height_m <= 0:
            raise ValueError("height_m must be positive when provided")
        if not 0.0 <= self.depth_valid_ratio <= 1.0:
            raise ValueError("depth_valid_ratio must be in [0, 1]")
        if self.frame != "xvisio_color":
            raise ValueError("grasp pose must use the xvisio_color frame")


@dataclass(frozen=True, slots=True)
class SpatialRank:
    detection_id: int
    centroid_xy: tuple[float, float]
    left_ordinal: int
    right_ordinal: int


@dataclass(frozen=True, slots=True)
class VisionDecision:
    status: DecisionStatus
    frame_id: int
    target: MaskCandidate | None
    pose: GraspPoseCamera | None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    stable_hits: int = 0
    window_size: int = 5
    selection_side: Literal["left", "right"] | None = None
    requested_ordinal: int | None = None
    spatial_ranks: tuple[SpatialRank, ...] = field(default_factory=tuple)
    candidates: tuple[MaskCandidate, ...] = field(default_factory=tuple)
    request_id: str | None = None
    selected_stable_id: int | None = None
    tracks: tuple[TrackedBottle, ...] = field(default_factory=tuple)
    captured_monotonic_ns: int = 0
    camera_serial: str = ""
    registration_id: str = ""
    motion_epoch: int = 0
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "searching",
            "rejected",
            "uncertain",
            "unstable",
            "ready",
        }:
            raise ValueError(f"unsupported decision status: {self.status}")
        if self.status == "ready" and self.pose is None:
            raise ValueError("ready decision requires a pose")
        if self.status == "ready" and self.target is None:
            raise ValueError("ready decision requires a unique target")
        if self.frame_id < 0 or self.stable_hits < 0 or self.window_size <= 0:
            raise ValueError("decision counters must be non-negative")
        if self.stable_hits > self.window_size:
            raise ValueError("stable_hits cannot exceed window_size")
        if self.selection_side not in {None, "left", "right"}:
            raise ValueError("selection_side must be left, right, or None")
        if self.requested_ordinal is not None and self.requested_ordinal <= 0:
            raise ValueError("requested_ordinal must be positive")
        if self.request_id is not None and not self.request_id:
            raise ValueError("request_id must be non-empty when provided")
        if self.selected_stable_id is not None and not 1 <= self.selected_stable_id <= 5:
            raise ValueError("selected_stable_id must be in [1, 5]")
        if self.captured_monotonic_ns < 0 or self.motion_epoch < 0:
            raise ValueError("evidence time and motion epoch must be non-negative")
        if self.evidence_id is not None and not self.evidence_id:
            raise ValueError("evidence_id must be non-empty when provided")
        assigned_ids = [
            track.stable_id for track in self.tracks if track.stable_id is not None
        ]
        if len(assigned_ids) != len(set(assigned_ids)):
            raise ValueError("tracked bottle stable IDs must be unique")
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "spatial_ranks", tuple(self.spatial_ranks))
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "tracks", tuple(self.tracks))


VisionResult = VisionDecision


__all__ = [
    "DecisionStatus",
    "GraspPoseCamera",
    "MaskCandidate",
    "SpatialRank",
    "TrackState",
    "TrackedBottle",
    "VisionDecision",
    "VisionResult",
]
