"""Immutable contracts shared by active-view planning modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from .types import FrameStamp, InvalidDataError


def _readonly_vector(value: Any, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.shape != shape or not np.isfinite(array).all():
        raise InvalidDataError(f"{name} must be a finite array with shape {shape}")
    array.setflags(write=False)
    return array


def _evidence_ids(values: Any, *, allow_empty: bool = False) -> tuple[str, ...]:
    try:
        result = tuple(values)
    except TypeError as exc:
        raise InvalidDataError("evidence_ids must be a sequence") from exc
    if (not result and not allow_empty) or any(
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != len("sha256:") + 64
        or any(character not in "0123456789abcdef" for character in value[7:])
        for value in result
    ):
        raise InvalidDataError("evidence_ids must contain content-addressed sha256 IDs")
    return result


def _readonly_convex_polygon(value: Any) -> np.ndarray:
    polygon = np.array(value, dtype=float, copy=True)
    if polygon.ndim != 2 or polygon.shape[1:] != (2,) or polygon.shape[0] < 3:
        raise InvalidDataError("coverage polygon must contain at least three XY vertices")
    if not np.isfinite(polygon).all():
        raise InvalidDataError("coverage polygon must contain only finite values")
    edges = np.roll(polygon, -1, axis=0) - polygon
    next_edges = np.roll(edges, -1, axis=0)
    turns = edges[:, 0] * next_edges[:, 1] - edges[:, 1] * next_edges[:, 0]
    if np.any(np.abs(turns) <= 1e-12) or not (
        np.all(turns > 0.0) or np.all(turns < 0.0)
    ):
        raise InvalidDataError("coverage polygon must be strictly convex")
    polygon.setflags(write=False)
    return polygon


@dataclass(frozen=True)
class CoarseTargetEstimate:
    """A table-plane target estimate used only for observation planning."""

    identity_id: int
    center_xy_m: np.ndarray = field(compare=False)
    covariance_xy_m2: np.ndarray = field(compare=False)
    samples_xy_m: np.ndarray = field(compare=False)
    source_stamp: FrameStamp
    calibration_id: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.identity_id, bool)
            or not isinstance(self.identity_id, int)
            or self.identity_id < 0
        ):
            raise InvalidDataError("coarse target identity_id must be non-negative")
        center = _readonly_vector(self.center_xy_m, (2,), "center_xy_m")
        covariance = _readonly_vector(
            self.covariance_xy_m2,
            (2, 2),
            "covariance_xy_m2",
        )
        samples = np.array(self.samples_xy_m, dtype=float, copy=True)
        if samples.ndim != 2 or samples.shape[1:] != (2,) or samples.shape[0] < 3:
            raise InvalidDataError("samples_xy_m must contain at least three XY samples")
        if not np.isfinite(samples).all():
            raise InvalidDataError("samples_xy_m must contain only finite values")
        if not np.allclose(covariance, covariance.T, atol=1e-12):
            raise InvalidDataError("coarse target covariance must be symmetric")
        if float(np.min(np.linalg.eigvalsh(covariance))) < -1e-12:
            raise InvalidDataError("coarse target covariance must be positive semidefinite")
        if not isinstance(self.source_stamp, FrameStamp):
            raise InvalidDataError("coarse target requires frame provenance")
        calibration_id = _evidence_ids((self.calibration_id,))[0]

        samples.setflags(write=False)
        object.__setattr__(self, "center_xy_m", center)
        object.__setattr__(self, "covariance_xy_m2", covariance)
        object.__setattr__(self, "samples_xy_m", samples)
        object.__setattr__(self, "calibration_id", calibration_id)


@dataclass(frozen=True)
class ObservationPose:
    """A pre-taught and independently path-validated camera observation pose."""

    pose_id: str
    joints_deg: np.ndarray = field(compare=False)
    t_base_from_flange: np.ndarray = field(compare=False)
    coverage_polygon_xy_m: np.ndarray = field(compare=False)
    allowed_start_pose_ids: tuple[str, ...]
    path_validation_id: str
    calibration_id: str
    joint_tolerance_deg: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.pose_id, str) or not self.pose_id:
            raise InvalidDataError("observation pose_id must be a non-empty string")
        joints = _readonly_vector(self.joints_deg, (6,), "observation joints_deg")
        transform = _readonly_vector(
            self.t_base_from_flange,
            (4, 4),
            "t_base_from_flange",
        )
        if not np.allclose(transform[3], [0.0, 0.0, 0.0, 1.0], atol=1e-9):
            raise InvalidDataError("observation transform must be homogeneous")
        rotation = transform[:3, :3]
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6) or not np.isclose(
            np.linalg.det(rotation), 1.0, atol=1e-6
        ):
            raise InvalidDataError("observation transform rotation must be rigid")
        polygon = _readonly_convex_polygon(self.coverage_polygon_xy_m)
        starts = tuple(self.allowed_start_pose_ids)
        if not starts or any(not isinstance(item, str) or not item for item in starts):
            raise InvalidDataError("observation pose requires allowed start pose IDs")
        if len(set(starts)) != len(starts):
            raise InvalidDataError("allowed start pose IDs must be unique")
        path_id, calibration_id = _evidence_ids(
            (self.path_validation_id, self.calibration_id)
        )
        tolerance = float(self.joint_tolerance_deg)
        if not np.isfinite(tolerance) or tolerance <= 0.0:
            raise InvalidDataError("joint tolerance must be finite and positive")

        object.__setattr__(self, "joints_deg", joints)
        object.__setattr__(self, "t_base_from_flange", transform)
        object.__setattr__(self, "coverage_polygon_xy_m", polygon)
        object.__setattr__(self, "allowed_start_pose_ids", starts)
        object.__setattr__(self, "path_validation_id", path_id)
        object.__setattr__(self, "calibration_id", calibration_id)
        object.__setattr__(self, "joint_tolerance_deg", tolerance)


@dataclass(frozen=True)
class TablePlane:
    """A calibrated table plane expressed as ``normal · point + offset = 0``."""

    normal_base: np.ndarray = field(compare=False)
    offset_m: float
    position_rmse_m: float
    calibration_id: str
    validated: bool

    def __post_init__(self) -> None:
        normal = np.array(self.normal_base, dtype=float, copy=True)
        if normal.shape != (3,) or not np.isfinite(normal).all():
            raise InvalidDataError("table normal must be a finite 3-vector")
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-12:
            raise InvalidDataError("table normal must be non-zero")
        if not np.isfinite(self.offset_m):
            raise InvalidDataError("table offset must be finite")
        if not np.isfinite(self.position_rmse_m) or self.position_rmse_m <= 0.0:
            raise InvalidDataError("table position RMSE must be finite and positive")
        calibration_id = _evidence_ids((self.calibration_id,))[0]
        if not isinstance(self.validated, bool):
            raise InvalidDataError("table validation state must be a boolean")

        normal /= norm
        normal.setflags(write=False)
        object.__setattr__(self, "normal_base", normal)
        object.__setattr__(self, "offset_m", float(self.offset_m) / norm)
        object.__setattr__(self, "position_rmse_m", float(self.position_rmse_m))
        object.__setattr__(self, "calibration_id", calibration_id)


@dataclass(frozen=True)
class DepthQuality:
    """D435 target-depth quality, independent of any motion decision."""

    valid_points: int
    central_fraction: float
    center_d435_m: Optional[np.ndarray] = field(compare=False)
    center_base_m: Optional[np.ndarray] = field(compare=False)
    mad_m: Optional[np.ndarray] = field(compare=False)
    acceptable: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.valid_points, bool)
            or not isinstance(self.valid_points, int)
            or self.valid_points < 0
        ):
            raise InvalidDataError("depth valid_points must be a non-negative integer")
        fraction = float(self.central_fraction)
        if not np.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
            raise InvalidDataError("depth central_fraction must be within [0, 1]")
        if not isinstance(self.acceptable, bool):
            raise InvalidDataError("depth acceptable must be a boolean")
        reasons = tuple(self.reasons)
        if any(not isinstance(reason, str) or not reason for reason in reasons):
            raise InvalidDataError("depth quality reasons must be non-empty strings")
        if self.acceptable and reasons:
            raise InvalidDataError("acceptable depth quality cannot have rejection reasons")
        if not self.acceptable and not reasons:
            raise InvalidDataError("unacceptable depth quality requires rejection reasons")

        values = (self.center_d435_m, self.center_base_m, self.mad_m)
        if any(value is None for value in values) and not all(value is None for value in values):
            raise InvalidDataError("depth centers and MAD must be present together")
        if all(value is None for value in values):
            if self.acceptable:
                raise InvalidDataError("acceptable depth quality requires finite geometry")
            center_d435 = center_base = mad = None
        else:
            center_d435 = _readonly_vector(self.center_d435_m, (3,), "center_d435_m")
            center_base = _readonly_vector(self.center_base_m, (3,), "center_base_m")
            mad = _readonly_vector(self.mad_m, (3,), "depth mad_m")
            if np.any(mad < 0.0):
                raise InvalidDataError("depth MAD must be non-negative")

        object.__setattr__(self, "central_fraction", fraction)
        object.__setattr__(self, "center_d435_m", center_d435)
        object.__setattr__(self, "center_base_m", center_base)
        object.__setattr__(self, "mad_m", mad)
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True)
class ObservationMoveProposal:
    kind: str
    identity_id: int
    source_stamp: FrameStamp
    expires_ns: int
    target_pose_id: Optional[str]
    joints_deg: Optional[np.ndarray] = field(compare=False)
    delta_base_m: Optional[np.ndarray] = field(compare=False)
    rotation_delta_rad: Optional[np.ndarray] = field(compare=False)
    evidence_ids: tuple[str, ...]
    reasons: tuple[str, ...]

    @classmethod
    def coarse(
        cls,
        *,
        identity_id: int,
        source_stamp: FrameStamp,
        expires_ns: int,
        target_pose_id: str,
        joints_deg: Any,
        evidence_ids: tuple[str, ...],
    ) -> "ObservationMoveProposal":
        return cls(
            kind="coarse_pose",
            identity_id=identity_id,
            source_stamp=source_stamp,
            expires_ns=expires_ns,
            target_pose_id=target_pose_id,
            joints_deg=joints_deg,
            delta_base_m=None,
            rotation_delta_rad=None,
            evidence_ids=evidence_ids,
            reasons=(),
        )

    @classmethod
    def rejected(
        cls,
        *,
        identity_id: int,
        source_stamp: FrameStamp,
        reasons: tuple[str, ...],
        evidence_ids: tuple[str, ...] = (),
    ) -> "ObservationMoveProposal":
        return cls(
            kind="none",
            identity_id=identity_id,
            source_stamp=source_stamp,
            expires_ns=source_stamp.monotonic_ns,
            target_pose_id=None,
            joints_deg=None,
            delta_base_m=None,
            rotation_delta_rad=None,
            evidence_ids=evidence_ids,
            reasons=reasons,
        )

    @classmethod
    def refine(
        cls,
        *,
        identity_id: int,
        source_stamp: FrameStamp,
        expires_ns: int,
        delta_base_m: Any,
        rotation_delta_rad: Any,
        evidence_ids: tuple[str, ...],
    ) -> "ObservationMoveProposal":
        return cls(
            kind="refine_delta",
            identity_id=identity_id,
            source_stamp=source_stamp,
            expires_ns=expires_ns,
            target_pose_id=None,
            joints_deg=None,
            delta_base_m=delta_base_m,
            rotation_delta_rad=rotation_delta_rad,
            evidence_ids=evidence_ids,
            reasons=(),
        )

    def __post_init__(self) -> None:
        if self.kind not in {"none", "coarse_pose", "refine_delta"}:
            raise InvalidDataError("active-view proposal kind is invalid")
        if (
            isinstance(self.identity_id, bool)
            or not isinstance(self.identity_id, int)
            or self.identity_id < 0
        ):
            raise InvalidDataError("active-view identity_id must be non-negative")
        if not isinstance(self.source_stamp, FrameStamp):
            raise InvalidDataError("active-view proposal requires frame provenance")
        if not isinstance(self.expires_ns, int) or self.expires_ns < self.source_stamp.monotonic_ns:
            raise InvalidDataError("active-view proposal expiry is invalid")
        reasons = tuple(self.reasons)
        if any(not isinstance(reason, str) or not reason for reason in reasons):
            raise InvalidDataError("active-view proposal reasons must be non-empty strings")

        if self.kind == "none":
            if any(
                value is not None
                for value in (
                    self.target_pose_id,
                    self.joints_deg,
                    self.delta_base_m,
                    self.rotation_delta_rad,
                )
            ):
                raise InvalidDataError("rejected proposal cannot contain a motion payload")
            if not reasons:
                raise InvalidDataError("rejected proposal requires reasons")
            evidence_ids = _evidence_ids(self.evidence_ids, allow_empty=True)
        elif self.kind == "coarse_pose":
            if not isinstance(self.target_pose_id, str) or not self.target_pose_id:
                raise InvalidDataError("coarse active-view proposal requires a target pose ID")
            if self.delta_base_m is not None or self.rotation_delta_rad is not None:
                raise InvalidDataError("coarse proposal cannot contain refinement deltas")
            if reasons:
                raise InvalidDataError("coarse proposal cannot contain rejection reasons")
            if self.expires_ns <= self.source_stamp.monotonic_ns:
                raise InvalidDataError("coarse proposal must expire after its source frame")
            object.__setattr__(
                self,
                "joints_deg",
                _readonly_vector(self.joints_deg, (6,), "joints_deg"),
            )
            evidence_ids = _evidence_ids(self.evidence_ids)
        else:
            if self.target_pose_id is not None or self.joints_deg is not None:
                raise InvalidDataError("refinement proposal cannot contain an absolute pose")
            if reasons:
                raise InvalidDataError("refinement proposal cannot contain rejection reasons")
            if self.expires_ns <= self.source_stamp.monotonic_ns:
                raise InvalidDataError("refinement proposal must expire after its source frame")
            object.__setattr__(
                self,
                "delta_base_m",
                _readonly_vector(self.delta_base_m, (3,), "delta_base_m"),
            )
            object.__setattr__(
                self,
                "rotation_delta_rad",
                _readonly_vector(self.rotation_delta_rad, (3,), "rotation_delta_rad"),
            )
            evidence_ids = _evidence_ids(self.evidence_ids)

        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "reasons", reasons)
