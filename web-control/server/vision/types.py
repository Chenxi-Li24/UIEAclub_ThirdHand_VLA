"""Validated immutable contracts shared by the offline vision pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Tuple

import numpy as np


class InvalidDataError(ValueError):
    """Raised when provenance or numeric vision data is unsafe to consume."""


def _readonly_array(value: Any, shape: Tuple[int, ...], name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.shape != shape:
        raise InvalidDataError(f"{name} must have shape {shape}, got {array.shape}")
    if not np.isfinite(array).all():
        raise InvalidDataError(f"{name} must contain only finite values")
    array.setflags(write=False)
    return array


def _readonly_vector(value: Any, name: str) -> np.ndarray:
    return _readonly_array(value, (3,), name)


@dataclass(frozen=True)
class FrameStamp:
    source: str
    frame_id: int
    monotonic_ns: int

    def __post_init__(self) -> None:
        if not self.source or self.frame_id < 0 or self.monotonic_ns < 0:
            raise InvalidDataError("invalid frame provenance")


@dataclass(frozen=True)
class CalibrationRef:
    calibration_id: str
    validated: bool
    reprojection_rmse_px: Optional[float]
    validation_notes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.calibration_id.startswith("sha256:"):
            raise InvalidDataError("calibration_id must be content-addressed with sha256:")
        if self.reprojection_rmse_px is not None:
            value = float(self.reprojection_rmse_px)
            if not np.isfinite(value) or value < 0.0:
                raise InvalidDataError("reprojection_rmse_px must be finite and non-negative")
            object.__setattr__(self, "reprojection_rmse_px", value)
        if self.validated and self.reprojection_rmse_px is None:
            raise InvalidDataError("validated calibration requires reprojection_rmse_px")
        object.__setattr__(self, "validation_notes", tuple(self.validation_notes))


@dataclass(frozen=True)
class PoseEstimate:
    xyz_m: np.ndarray = field(compare=False)
    covariance_m2: np.ndarray = field(compare=False)
    frame: str
    stamp: FrameStamp
    calibration_id: str

    def __post_init__(self) -> None:
        xyz = _readonly_vector(self.xyz_m, "xyz_m")
        covariance = _readonly_array(self.covariance_m2, (3, 3), "covariance_m2")
        if not self.frame:
            raise InvalidDataError("pose frame cannot be empty")
        if not self.calibration_id.startswith("sha256:"):
            raise InvalidDataError("pose calibration_id must start with sha256:")
        if not np.allclose(covariance, covariance.T, atol=1e-12):
            raise InvalidDataError("covariance_m2 must be symmetric")
        if np.min(np.linalg.eigvalsh(covariance)) < -1e-12:
            raise InvalidDataError("covariance_m2 must be positive semidefinite")
        object.__setattr__(self, "xyz_m", xyz)
        object.__setattr__(self, "covariance_m2", covariance)


@dataclass(frozen=True)
class TrackObservation:
    label: str
    confidence: float
    pose: PoseEstimate

    def __post_init__(self) -> None:
        confidence = float(self.confidence)
        if not self.label or not np.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise InvalidDataError("observation label/confidence is invalid")
        object.__setattr__(self, "confidence", confidence)


@dataclass(frozen=True)
class TrackState:
    track_id: int
    label: str
    pose: PoseEstimate
    velocity_mps: np.ndarray = field(compare=False)
    hits: int
    misses: int
    confirmed: bool
    last_seen_ns: int

    def __post_init__(self) -> None:
        if self.track_id < 0 or not self.label or self.hits < 1 or self.misses < 0:
            raise InvalidDataError("invalid track identity or counters")
        if self.last_seen_ns != self.pose.stamp.monotonic_ns:
            raise InvalidDataError("last_seen_ns must match the pose stamp")
        object.__setattr__(self, "velocity_mps", _readonly_vector(self.velocity_mps, "velocity_mps"))


@dataclass(frozen=True)
class SafetyDecision:
    approved: bool
    reasons: Tuple[str, ...]

    def __post_init__(self) -> None:
        reasons = tuple(str(reason) for reason in self.reasons)
        if self.approved and reasons:
            raise InvalidDataError("approved safety decision cannot have rejection reasons")
        if not self.approved and not reasons:
            raise InvalidDataError("rejected safety decision requires reasons")
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True)
class GraspCandidate:
    pregrasp_xyz_m: np.ndarray = field(compare=False)
    grasp_xyz_m: np.ndarray = field(compare=False)
    retreat_xyz_m: np.ndarray = field(compare=False)
    width_m: float
    score: float
    rejection_reasons: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "pregrasp_xyz_m", _readonly_vector(self.pregrasp_xyz_m, "pregrasp_xyz_m"))
        object.__setattr__(self, "grasp_xyz_m", _readonly_vector(self.grasp_xyz_m, "grasp_xyz_m"))
        object.__setattr__(self, "retreat_xyz_m", _readonly_vector(self.retreat_xyz_m, "retreat_xyz_m"))
        width = float(self.width_m)
        score = float(self.score)
        if not np.isfinite(width) or width <= 0.0 or not np.isfinite(score):
            raise InvalidDataError("candidate width and score must be finite; width must be positive")
        object.__setattr__(self, "width_m", width)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "rejection_reasons", tuple(self.rejection_reasons))


@dataclass(frozen=True)
class DryRunReport:
    approved: bool
    reasons: Tuple[str, ...]
    candidate_xyz_m: Optional[np.ndarray] = field(compare=False)
    score: Optional[float]
    target_track_id: int
    calibration_id: str

    def __post_init__(self) -> None:
        reasons = tuple(str(reason) for reason in self.reasons)
        if self.target_track_id < 0:
            raise InvalidDataError("target_track_id must be non-negative")
        if not self.calibration_id.startswith("sha256:"):
            raise InvalidDataError("report calibration_id must start with sha256:")
        if self.approved and (reasons or self.candidate_xyz_m is None or self.score is None):
            raise InvalidDataError("approved report requires a candidate and no rejection reasons")
        if not self.approved and not reasons:
            raise InvalidDataError("rejected report requires reasons")
        if self.candidate_xyz_m is not None:
            object.__setattr__(
                self,
                "candidate_xyz_m",
                _readonly_vector(self.candidate_xyz_m, "candidate_xyz_m"),
            )
        if self.score is not None:
            score = float(self.score)
            if not np.isfinite(score):
                raise InvalidDataError("report score must be finite")
            object.__setattr__(self, "score", score)
        object.__setattr__(self, "reasons", reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "reasons": list(self.reasons),
            "candidate_xyz_m": None
            if self.candidate_xyz_m is None
            else self.candidate_xyz_m.tolist(),
            "score": self.score,
            "target_track_id": self.target_track_id,
            "calibration_id": self.calibration_id,
        }

