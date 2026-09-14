"""Pure D435-mask geometry and temporal gates for top-down grasp previews."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from scipy.ndimage import binary_erosion

from .active_view_types import TablePlane, validated_evidence_ids
from .camera_models import PinholeCamera
from .depth_registration import RegisteredDepth
from .geometry import transform_points, validate_transform
from .types import FrameStamp, InvalidDataError


def _readonly(value: Any, shape: tuple[int, ...], name: str) -> np.ndarray:
    result = np.array(value, dtype=float, copy=True)
    if result.shape != shape or not np.isfinite(result).all():
        raise InvalidDataError(f"{name} must be a finite array with shape {shape}")
    result.setflags(write=False)
    return result


def _finite_positive(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise InvalidDataError(f"{name} must be finite and positive")
    result = float(value)
    if not np.isfinite(result) or result <= 0.0:
        raise InvalidDataError(f"{name} must be finite and positive")
    return result


@dataclass(frozen=True)
class GraspGeometryConfig:
    min_points: int
    erosion_px: int
    mad_scale: float
    noise_floor_m: float
    inner_roi_fraction: float
    min_central_fraction: float
    max_axis_mad_m: float
    min_object_height_m: float
    max_object_height_m: float
    min_gripper_width_m: float
    max_gripper_width_m: float
    grasp_width_margin_m: float
    pregrasp_clearance_m: float
    retreat_clearance_m: float
    workspace_min_m: np.ndarray = field(compare=False)
    workspace_max_m: np.ndarray = field(compare=False)
    stable_sample_count: int
    max_center_deviation_m: float
    max_temporal_axis_mad_m: float

    def __post_init__(self) -> None:
        for name in ("min_points", "stable_sample_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise InvalidDataError(f"{name} must be a positive integer")
        if (
            isinstance(self.erosion_px, bool)
            or not isinstance(self.erosion_px, int)
            or self.erosion_px < 0
        ):
            raise InvalidDataError("erosion_px must be a non-negative integer")
        positive_names = (
            "mad_scale",
            "noise_floor_m",
            "inner_roi_fraction",
            "min_central_fraction",
            "max_axis_mad_m",
            "min_object_height_m",
            "max_object_height_m",
            "min_gripper_width_m",
            "max_gripper_width_m",
            "grasp_width_margin_m",
            "pregrasp_clearance_m",
            "retreat_clearance_m",
            "max_center_deviation_m",
            "max_temporal_axis_mad_m",
        )
        for name in positive_names:
            object.__setattr__(self, name, _finite_positive(getattr(self, name), name))
        if self.inner_roi_fraction > 1.0 or self.min_central_fraction > 1.0:
            raise InvalidDataError("ROI fractions must be within (0, 1]")
        if self.min_object_height_m >= self.max_object_height_m:
            raise InvalidDataError("object height limits are invalid")
        if self.min_gripper_width_m >= self.max_gripper_width_m:
            raise InvalidDataError("gripper width limits are invalid")
        lower = _readonly(self.workspace_min_m, (3,), "workspace_min_m")
        upper = _readonly(self.workspace_max_m, (3,), "workspace_max_m")
        if not np.all(lower < upper):
            raise InvalidDataError("workspace bounds must strictly increase")
        object.__setattr__(self, "workspace_min_m", lower)
        object.__setattr__(self, "workspace_max_m", upper)


@dataclass(frozen=True)
class GraspCandidateGeometry:
    identity_id: int
    detection_id: int
    source_stamp: FrameStamp
    calibration_id: str
    evidence_ids: tuple[str, ...]
    grasp_xyz_m: np.ndarray = field(compare=False)
    pregrasp_xyz_m: np.ndarray = field(compare=False)
    retreat_xyz_m: np.ndarray = field(compare=False)
    yaw_rad: float
    width_m: float
    object_height_m: float
    valid_points: int
    central_fraction: float
    axis_mad_m: np.ndarray = field(compare=False)
    grasp_lumos_px: tuple[int, int]
    grasp_d435_px: tuple[float, float]

    def __post_init__(self) -> None:
        for name in ("identity_id", "detection_id", "valid_points"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidDataError(f"{name} must be a non-negative integer")
        if not isinstance(self.source_stamp, FrameStamp):
            raise InvalidDataError("grasp candidate requires frame provenance")
        calibration_id = validated_evidence_ids((self.calibration_id,))[0]
        evidence_ids = validated_evidence_ids(self.evidence_ids)
        for name in ("grasp_xyz_m", "pregrasp_xyz_m", "retreat_xyz_m", "axis_mad_m"):
            object.__setattr__(self, name, _readonly(getattr(self, name), (3,), name))
        finite = np.asarray(
            [self.yaw_rad, self.width_m, self.object_height_m, self.central_fraction],
            dtype=float,
        )
        if not np.isfinite(finite).all():
            raise InvalidDataError("grasp geometry scalars must be finite")
        if self.width_m <= 0.0 or self.object_height_m <= 0.0:
            raise InvalidDataError("grasp width and object height must be positive")
        if not 0.0 <= self.central_fraction <= 1.0:
            raise InvalidDataError("central_fraction must be within [0, 1]")
        if np.any(self.axis_mad_m < 0.0):
            raise InvalidDataError("axis MAD must be non-negative")
        lumos = tuple(self.grasp_lumos_px)
        d435 = tuple(float(item) for item in self.grasp_d435_px)
        if (
            len(lumos) != 2
            or any(
                isinstance(item, bool) or not isinstance(item, int) or item < 0
                for item in lumos
            )
            or len(d435) != 2
            or not np.isfinite(d435).all()
        ):
            raise InvalidDataError("grasp pixels are invalid")
        object.__setattr__(self, "calibration_id", calibration_id)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "yaw_rad", float(self.yaw_rad))
        object.__setattr__(self, "width_m", float(self.width_m))
        object.__setattr__(self, "object_height_m", float(self.object_height_m))
        object.__setattr__(self, "central_fraction", float(self.central_fraction))
        object.__setattr__(self, "grasp_lumos_px", lumos)
        object.__setattr__(self, "grasp_d435_px", d435)


@dataclass(frozen=True)
class GraspGeometryEvaluation:
    candidate: GraspCandidateGeometry | None
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        blockers = tuple(dict.fromkeys(self.blockers))
        if any(not isinstance(item, str) or not item for item in blockers):
            raise InvalidDataError("grasp blockers must be non-empty strings")
        if self.candidate is None and not blockers:
            raise InvalidDataError("missing grasp candidate requires blockers")
        object.__setattr__(self, "blockers", blockers)

    @property
    def allowed(self) -> bool:
        return self.candidate is not None and not self.blockers

    def with_identity(self, identity_id: int) -> GraspGeometryEvaluation:
        if self.candidate is None:
            return self
        return replace(self, candidate=replace(self.candidate, identity_id=identity_id))


def _robust_inliers(points: np.ndarray, config: GraspGeometryConfig) -> np.ndarray:
    center = np.median(points, axis=0)
    deviation = np.abs(points - center)
    mad = np.median(deviation, axis=0)
    limits = np.maximum(config.mad_scale * 1.4826 * mad, config.noise_floor_m)
    return np.all(deviation <= limits, axis=1)


def _symmetric_yaw(vector_xy: np.ndarray) -> float:
    yaw = float(np.arctan2(vector_xy[1], vector_xy[0]))
    return float((yaw + np.pi / 2.0) % np.pi - np.pi / 2.0)


def evaluate_top_down_grasp(
    *,
    identity_id: int,
    detection_id: int,
    registered: RegisteredDepth,
    target_mask: Any,
    d435: PinholeCamera,
    t_d435_from_lumos: Any,
    t_base_from_lumos: Any,
    table: TablePlane,
    source_stamp: FrameStamp,
    calibration_id: str,
    evidence_ids: tuple[str, ...],
    config: GraspGeometryConfig,
    d435_instance_mask: Any = None,
) -> GraspGeometryEvaluation:
    """Evaluate one mask-depth sample; never produce an execution command."""

    if not isinstance(registered, RegisteredDepth):
        raise InvalidDataError("grasp geometry requires registered D435 depth")
    if not isinstance(d435, PinholeCamera):
        raise InvalidDataError("grasp geometry requires a D435 camera model")
    if d435_instance_mask is None:
        instance_mask = None
    else:
        instance_mask = np.asarray(d435_instance_mask)
        if instance_mask.dtype != np.bool_ or instance_mask.shape != (
            d435.height,
            d435.width,
        ):
            raise InvalidDataError("D435 instance mask must use native boolean pixels")
    if not isinstance(table, TablePlane) or not table.validated:
        return GraspGeometryEvaluation(None, ("table_not_validated",))
    if table.calibration_id != calibration_id:
        return GraspGeometryEvaluation(None, ("table_calibration_mismatch",))
    validated_evidence_ids((calibration_id, *evidence_ids))
    mask = np.asarray(target_mask)
    if mask.dtype != np.bool_ or mask.shape != registered.valid.shape:
        raise InvalidDataError("target mask must be boolean and match registered depth")
    usable = binary_erosion(mask, iterations=config.erosion_px) if config.erosion_px else mask
    selected = usable & registered.valid
    rows, cols = np.nonzero(selected)
    points_lumos = np.asarray(registered.points_lumos_m[selected], dtype=float)
    if len(points_lumos) < config.min_points:
        return GraspGeometryEvaluation(None, ("insufficient_depth_points",))
    inlier_mask = _robust_inliers(points_lumos, config)
    points_lumos = points_lumos[inlier_mask]
    rows = rows[inlier_mask]
    cols = cols[inlier_mask]
    if len(points_lumos) < config.min_points:
        return GraspGeometryEvaluation(None, ("insufficient_depth_points",))

    t_d435 = validate_transform(t_d435_from_lumos)
    t_base = validate_transform(t_base_from_lumos)
    points_d435 = transform_points(t_d435, points_lumos)
    uv_d435, projected = d435.project(points_d435)
    if not np.any(projected):
        return GraspGeometryEvaluation(None, ("no_projectable_depth_points",))
    points_lumos = points_lumos[projected]
    points_d435 = points_d435[projected]
    uv_d435 = uv_d435[projected]
    rows = rows[projected]
    cols = cols[projected]
    if instance_mask is not None:
        rounded = np.rint(uv_d435).astype(np.int64)
        in_frame = (
            (rounded[:, 0] >= 0)
            & (rounded[:, 0] < d435.width)
            & (rounded[:, 1] >= 0)
            & (rounded[:, 1] < d435.height)
        )
        supported = np.zeros(len(rounded), dtype=bool)
        supported[in_frame] = instance_mask[
            rounded[in_frame, 1], rounded[in_frame, 0]
        ]
        points_lumos = points_lumos[supported]
        points_d435 = points_d435[supported]
        uv_d435 = uv_d435[supported]
        rows = rows[supported]
        cols = cols[supported]
        if len(points_lumos) < config.min_points:
            return GraspGeometryEvaluation(None, ("insufficient_depth_points",))
    points_base = transform_points(t_base, points_lumos)

    horizontal_margin = d435.width * (1.0 - config.inner_roi_fraction) * 0.5
    vertical_margin = d435.height * (1.0 - config.inner_roi_fraction) * 0.5
    central = (
        (uv_d435[:, 0] >= horizontal_margin)
        & (uv_d435[:, 0] < d435.width - horizontal_margin)
        & (uv_d435[:, 1] >= vertical_margin)
        & (uv_d435[:, 1] < d435.height - vertical_margin)
    )
    central_fraction = float(np.count_nonzero(central) / len(points_base))
    center = np.median(points_base, axis=0)
    axis_mad = np.median(np.abs(points_base - center), axis=0)
    nearest = int(np.argmin(np.linalg.norm(points_base - center, axis=1)))
    grasp_xyz = np.asarray(points_base[nearest], dtype=float)
    grasp_lumos_px = (int(cols[nearest]), int(rows[nearest]))
    grasp_d435_px = tuple(float(item) for item in uv_d435[nearest])

    planar = points_base[:, :2] - np.median(points_base[:, :2], axis=0)
    covariance = np.cov(planar, rowvar=False) if len(planar) > 1 else np.eye(2) * 1e-12
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    major = eigenvectors[:, int(np.argmax(eigenvalues))]
    minor = np.array([-major[1], major[0]])
    minor_coordinate = planar @ minor
    width = float(
        np.quantile(minor_coordinate, 0.95)
        - np.quantile(minor_coordinate, 0.05)
        + config.grasp_width_margin_m
    )
    signed_height = points_base @ table.normal_base + table.offset_m
    object_height = float(np.quantile(signed_height, 0.95))
    center_height = float(np.median(signed_height))
    pregrasp = grasp_xyz + table.normal_base * config.pregrasp_clearance_m
    retreat = grasp_xyz + table.normal_base * config.retreat_clearance_m

    blockers: list[str] = []
    if len(points_base) < config.min_points:
        blockers.append("insufficient_depth_points")
    if central_fraction < config.min_central_fraction:
        blockers.append("insufficient_central_coverage")
    if center_height < config.min_object_height_m:
        blockers.append("object_too_close_to_table")
    if object_height > config.max_object_height_m:
        blockers.append("object_height_exceeded")
    if not config.min_gripper_width_m <= width <= config.max_gripper_width_m:
        blockers.append("grasp_width_out_of_range")
    waypoints = np.vstack((grasp_xyz, pregrasp, retreat))
    if not (
        np.all(config.workspace_min_m <= waypoints)
        and np.all(waypoints <= config.workspace_max_m)
    ):
        blockers.append("outside_workspace")

    candidate = GraspCandidateGeometry(
        identity_id=identity_id,
        detection_id=detection_id,
        source_stamp=source_stamp,
        calibration_id=calibration_id,
        evidence_ids=evidence_ids,
        grasp_xyz_m=grasp_xyz,
        pregrasp_xyz_m=pregrasp,
        retreat_xyz_m=retreat,
        yaw_rad=_symmetric_yaw(major),
        width_m=max(width, np.finfo(float).eps),
        object_height_m=max(object_height, np.finfo(float).eps),
        valid_points=len(points_base),
        central_fraction=central_fraction,
        axis_mad_m=axis_mad,
        grasp_lumos_px=grasp_lumos_px,
        grasp_d435_px=grasp_d435_px,
    )
    return GraspGeometryEvaluation(candidate, tuple(blockers))


def _preview_id(candidate: GraspCandidateGeometry, center: np.ndarray, samples: int) -> str:
    payload = {
        "schema_version": 1,
        "identity_id": candidate.identity_id,
        "detection_id": candidate.detection_id,
        "frame_id": candidate.source_stamp.frame_id,
        "monotonic_ns": candidate.source_stamp.monotonic_ns,
        "calibration_id": candidate.calibration_id,
        "evidence_ids": list(candidate.evidence_ids),
        "grasp_xyz_m": center.tolist(),
        "yaw_rad": candidate.yaw_rad,
        "width_m": candidate.width_m,
        "stable_samples": samples,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class GraspPreviewStatus:
    preview_id: str | None
    candidate: GraspCandidateGeometry | None
    grasp_xyz_m: np.ndarray | None = field(compare=False)
    stable_samples: int
    allowed: bool
    blockers: tuple[str, ...]

    @property
    def identity_id(self) -> int | None:
        return None if self.candidate is None else self.candidate.identity_id

    def __post_init__(self) -> None:
        if isinstance(self.stable_samples, bool) or not isinstance(self.stable_samples, int):
            raise InvalidDataError("stable_samples must be an integer")
        if self.stable_samples < 0 or not isinstance(self.allowed, bool):
            raise InvalidDataError("grasp preview state is invalid")
        blockers = tuple(dict.fromkeys(self.blockers))
        if self.allowed and (blockers or self.candidate is None or self.preview_id is None):
            raise InvalidDataError("allowed preview requires complete unblocked geometry")
        if not self.allowed and not blockers:
            raise InvalidDataError("blocked preview requires reasons")
        if self.candidate is None:
            if self.grasp_xyz_m is not None or self.preview_id is not None:
                raise InvalidDataError("missing candidate cannot expose preview geometry")
        else:
            object.__setattr__(
                self,
                "grasp_xyz_m",
                _readonly(self.grasp_xyz_m, (3,), "grasp_xyz_m"),
            )
            validated_evidence_ids((self.preview_id,))
        object.__setattr__(self, "blockers", blockers)

    def to_dict(self) -> dict[str, Any]:
        candidate = self.candidate
        return {
            "preview_id": self.preview_id,
            "identity_id": self.identity_id,
            "detection_id": None if candidate is None else candidate.detection_id,
            "frame": None if candidate is None else "robot_base",
            "calibration_id": None if candidate is None else candidate.calibration_id,
            "evidence_ids": [] if candidate is None else list(candidate.evidence_ids),
            "grasp_xyz_m": None if self.grasp_xyz_m is None else self.grasp_xyz_m.tolist(),
            "pregrasp_xyz_m": None if candidate is None else candidate.pregrasp_xyz_m.tolist(),
            "retreat_xyz_m": None if candidate is None else candidate.retreat_xyz_m.tolist(),
            "grasp_lumos_px": None if candidate is None else list(candidate.grasp_lumos_px),
            "grasp_d435_px": None if candidate is None else list(candidate.grasp_d435_px),
            "yaw_rad": None if candidate is None else candidate.yaw_rad,
            "width_m": None if candidate is None else candidate.width_m,
            "object_height_m": None if candidate is None else candidate.object_height_m,
            "valid_points": 0 if candidate is None else candidate.valid_points,
            "central_fraction": 0.0 if candidate is None else candidate.central_fraction,
            "stable_samples": self.stable_samples,
            "allowed": self.allowed,
            "blockers": list(self.blockers),
        }

    def with_blockers(self, *reasons: str) -> GraspPreviewStatus:
        combined = tuple(dict.fromkeys((*self.blockers, *reasons)))
        if not combined:
            return self
        return replace(self, allowed=False, blockers=combined)


class GraspPreviewAccumulator:
    """Bound a short stable window to one identity and evidence set."""

    def __init__(self, config: GraspGeometryConfig) -> None:
        if not isinstance(config, GraspGeometryConfig):
            raise InvalidDataError("grasp preview accumulator requires geometry config")
        self.config = config
        self._key: tuple[Any, ...] | None = None
        self._window: deque[GraspGeometryEvaluation] = deque(
            maxlen=config.stable_sample_count
        )

    def update(self, evaluation: GraspGeometryEvaluation) -> GraspPreviewStatus:
        if not isinstance(evaluation, GraspGeometryEvaluation):
            raise InvalidDataError("grasp preview update requires one geometry evaluation")
        candidate = evaluation.candidate
        if candidate is None:
            self._key = None
            self._window.clear()
            return GraspPreviewStatus(None, None, None, 0, False, evaluation.blockers)
        key = (
            candidate.identity_id,
            candidate.calibration_id,
            candidate.evidence_ids,
        )
        if key != self._key:
            self._key = key
            self._window.clear()
        self._window.append(evaluation)
        candidates = tuple(item.candidate for item in self._window)
        centers = np.vstack([item.grasp_xyz_m for item in candidates if item is not None])
        center = np.median(centers, axis=0)
        blockers = list(
            dict.fromkeys(reason for item in self._window for reason in item.blockers)
        )
        if len(self._window) < self.config.stable_sample_count:
            blockers.append("depth_not_stable")
        else:
            deviation = np.linalg.norm(centers - center, axis=1)
            temporal_mad = np.median(np.abs(centers - center), axis=0)
            if (
                float(np.max(deviation)) > self.config.max_center_deviation_m
                or np.any(temporal_mad > self.config.max_temporal_axis_mad_m)
            ):
                blockers.append("depth_temporally_unstable")
        blockers = list(dict.fromkeys(blockers))
        preview_id = _preview_id(candidate, center, len(self._window))
        return GraspPreviewStatus(
            preview_id=preview_id,
            candidate=candidate,
            grasp_xyz_m=center,
            stable_samples=len(self._window),
            allowed=not blockers,
            blockers=tuple(blockers),
        )


__all__ = [
    "GraspCandidateGeometry",
    "GraspGeometryConfig",
    "GraspGeometryEvaluation",
    "GraspPreviewAccumulator",
    "GraspPreviewStatus",
    "evaluate_top_down_grasp",
]
