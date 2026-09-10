"""Immutable contracts for advisory active-view calculations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.core.types import FrameStamp


def _vector(value: Any, length: int, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != (length,) or not np.isfinite(array).all():
        raise InputValidationError(f"{name} must be a finite {length}-vector")
    result = np.array(array, copy=True)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class ActiveViewConfig:
    inner_roi_fraction: float
    min_depth_points: int
    min_central_fraction: float
    max_axis_mad_m: float
    max_translation_m: float
    proposal_ttl_ns: int

    def __post_init__(self) -> None:
        if not np.isfinite(self.inner_roi_fraction) or not 0.0 < self.inner_roi_fraction <= 1.0:
            raise InputValidationError("inner ROI fraction must be within (0, 1]")
        if not np.isfinite(self.min_central_fraction) or not 0.0 < self.min_central_fraction <= 1.0:
            raise InputValidationError("minimum central fraction must be within (0, 1]")
        if isinstance(self.min_depth_points, bool) or not isinstance(self.min_depth_points, int) or self.min_depth_points < 1:
            raise InputValidationError("minimum depth points must be positive")
        if not np.isfinite(self.max_axis_mad_m) or self.max_axis_mad_m <= 0.0:
            raise InputValidationError("maximum axis MAD must be positive")
        if not np.isfinite(self.max_translation_m) or self.max_translation_m <= 0.0:
            raise InputValidationError("maximum translation must be positive")
        if isinstance(self.proposal_ttl_ns, bool) or not isinstance(self.proposal_ttl_ns, int) or not 0 < self.proposal_ttl_ns <= 1_000_000_000:
            raise InputValidationError("proposal TTL must be within one second")


@dataclass(frozen=True)
class CoarseTargetEstimate:
    center_xy_m: np.ndarray = field(compare=False, repr=False)
    covariance_xy_m2: np.ndarray = field(compare=False, repr=False)
    stamp: FrameStamp
    calibration_id: str

    def __post_init__(self) -> None:
        center = _vector(self.center_xy_m, 2, "coarse target center")
        covariance = np.asarray(self.covariance_xy_m2, dtype=float)
        if covariance.shape != (2, 2) or not np.isfinite(covariance).all():
            raise InputValidationError("coarse target covariance must be finite 2x2")
        if not np.allclose(covariance, covariance.T, atol=1e-12):
            raise InputValidationError("coarse target covariance must be symmetric")
        if float(np.min(np.linalg.eigvalsh(covariance))) < -1e-12:
            raise InputValidationError("coarse target covariance must be positive semidefinite")
        covariance_copy = np.array(covariance, copy=True)
        covariance_copy.setflags(write=False)
        if not isinstance(self.stamp, FrameStamp):
            raise InputValidationError("coarse target stamp is invalid")
        if not isinstance(self.calibration_id, str) or not self.calibration_id:
            raise InputValidationError("coarse target calibration ID is required")
        object.__setattr__(self, "center_xy_m", center)
        object.__setattr__(self, "covariance_xy_m2", covariance_copy)


@dataclass(frozen=True)
class ObservationPose:
    pose_id: str
    joints_deg: np.ndarray = field(compare=False, repr=False)
    coverage_min_xy_m: np.ndarray = field(compare=False, repr=False)
    coverage_max_xy_m: np.ndarray = field(compare=False, repr=False)
    validated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.pose_id, str) or not self.pose_id:
            raise InputValidationError("observation pose ID is required")
        joints = _vector(self.joints_deg, 6, "observation joints")
        lower = _vector(self.coverage_min_xy_m, 2, "coverage minimum")
        upper = _vector(self.coverage_max_xy_m, 2, "coverage maximum")
        if np.any(lower >= upper):
            raise InputValidationError("observation coverage minimum must be below maximum")
        if not isinstance(self.validated, bool):
            raise InputValidationError("observation pose validated flag must be boolean")
        object.__setattr__(self, "joints_deg", joints)
        object.__setattr__(self, "coverage_min_xy_m", lower)
        object.__setattr__(self, "coverage_max_xy_m", upper)

    def covers(self, target_xy_m: np.ndarray) -> bool:
        return bool(
            self.validated
            and np.all(self.coverage_min_xy_m <= target_xy_m)
            and np.all(target_xy_m <= self.coverage_max_xy_m)
        )


@dataclass(frozen=True)
class DepthQuality:
    valid_points: int
    central_fraction: float
    center_d435_m: np.ndarray = field(compare=False, repr=False)
    center_output_m: np.ndarray = field(compare=False, repr=False)
    mad_output_m: np.ndarray = field(compare=False, repr=False)
    acceptable: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.valid_points, bool) or not isinstance(self.valid_points, int) or self.valid_points < 0:
            raise InputValidationError("valid depth point count must be non-negative")
        fraction = float(self.central_fraction)
        if not np.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
            raise InputValidationError("central fraction must be within [0, 1]")
        object.__setattr__(self, "central_fraction", fraction)
        object.__setattr__(self, "center_d435_m", _vector(self.center_d435_m, 3, "D435 center"))
        object.__setattr__(self, "center_output_m", _vector(self.center_output_m, 3, "output center"))
        object.__setattr__(self, "mad_output_m", _vector(self.mad_output_m, 3, "output MAD"))
        if not isinstance(self.acceptable, bool):
            raise InputValidationError("depth quality acceptable flag must be boolean")
        object.__setattr__(self, "reasons", tuple(dict.fromkeys(self.reasons)))


@dataclass(frozen=True)
class ObservationProposal:
    proposal_id: str
    kind: str
    identity_id: Optional[int]
    target_pose_id: Optional[str]
    joints_deg: Optional[np.ndarray] = field(compare=False, repr=False)
    delta_output_m: np.ndarray = field(compare=False, repr=False)
    source_frame_id: int
    expires_ns: int
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise InputValidationError("proposal ID is required")
        if self.kind not in {"catalog", "refinement", "none"}:
            raise InputValidationError("proposal kind is invalid")
        if self.identity_id is not None and (
            isinstance(self.identity_id, bool)
            or not isinstance(self.identity_id, int)
            or self.identity_id < 0
        ):
            raise InputValidationError("proposal identity ID is invalid")
        if self.joints_deg is not None:
            object.__setattr__(self, "joints_deg", _vector(self.joints_deg, 6, "proposal joints"))
        object.__setattr__(self, "delta_output_m", _vector(self.delta_output_m, 3, "proposal delta"))
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (self.source_frame_id, self.expires_ns)):
            raise InputValidationError("proposal frame and expiry must be non-negative integers")
        object.__setattr__(self, "reasons", tuple(dict.fromkeys(self.reasons)))

