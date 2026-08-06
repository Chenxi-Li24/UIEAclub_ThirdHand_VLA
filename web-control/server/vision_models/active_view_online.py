"""Strict configuration boundary for hardware-independent active-view planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from vision.active_view_types import ObservationPose, TablePlane
from vision.types import InvalidDataError


_TOP_LEVEL_KEYS = {
    "schema_version",
    "dry_run_enabled",
    "active_view_execution_enabled",
    "table_plane",
    "quality",
    "motion_proposals",
    "observation_poses",
}
_TABLE_KEYS = {
    "normal_base",
    "offset_m",
    "position_rmse_m",
    "calibration_id",
    "validated",
}
_QUALITY_KEYS = {
    "inner_roi_fraction",
    "coverage_margin_m",
    "min_depth_points",
    "min_central_fraction",
    "stable_sample_count",
    "max_center_deviation_m",
    "max_axis_mad_m",
}
_MOTION_KEYS = {
    "max_translation_m",
    "max_rotation_deg",
    "max_refinement_steps",
    "proposal_ttl_ms",
}
_POSE_REQUIRED_KEYS = {
    "pose_id",
    "joints_deg",
    "t_base_from_flange",
    "coverage_polygon_xy_m",
    "allowed_start_pose_ids",
    "path_validation_id",
    "calibration_id",
}
_POSE_OPTIONAL_KEYS = {"joint_tolerance_deg"}


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidDataError(f"{name} must be a mapping")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    required: set[str],
    name: str,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    keys = set(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise InvalidDataError(f"{name} is missing keys: {sorted(missing)}")
    if unknown:
        raise InvalidDataError(f"{name} has unknown keys: {sorted(unknown)}")


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidDataError(f"{name} must be an explicit boolean")
    return value


def _positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise InvalidDataError(f"{name} must be finite and positive")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidDataError(f"{name} must be finite and positive") from exc
    if not np.isfinite(result) or result <= 0.0:
        raise InvalidDataError(f"{name} must be finite and positive")
    return result


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise InvalidDataError(f"{name} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidDataError(f"{name} must be finite") from exc
    if not np.isfinite(result):
        raise InvalidDataError(f"{name} must be finite")
    return result


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidDataError(f"{name} must be a positive integer")
    return value


def _fraction(value: Any, name: str) -> float:
    result = _positive_float(value, name)
    if result > 1.0:
        raise InvalidDataError(f"{name} must be within (0, 1]")
    return result


@dataclass(frozen=True)
class ActiveViewConfig:
    dry_run_enabled: bool
    execution_enabled: bool
    table_plane: TablePlane
    inner_roi_fraction: float
    coverage_margin_m: float
    min_depth_points: int
    min_central_fraction: float
    stable_sample_count: int
    max_center_deviation_m: float
    max_axis_mad_m: float
    max_translation_m: float
    max_rotation_rad: float
    max_refinement_steps: int
    proposal_ttl_ns: int
    observation_poses: tuple[ObservationPose, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.dry_run_enabled, bool):
            raise InvalidDataError("active-view dry-run state must be a boolean")
        if self.execution_enabled is not False:
            raise InvalidDataError("active-view execution must remain disabled")
        if not isinstance(self.table_plane, TablePlane):
            raise InvalidDataError("active-view config requires a table plane")
        inner_roi_fraction = _fraction(
            self.inner_roi_fraction,
            "active-view inner ROI fraction",
        )
        coverage_margin_m = _positive_float(
            self.coverage_margin_m,
            "active-view coverage margin",
        )
        min_depth_points = _positive_int(
            self.min_depth_points,
            "active-view minimum depth points",
        )
        min_central_fraction = _fraction(
            self.min_central_fraction,
            "active-view minimum central fraction",
        )
        stable_sample_count = _positive_int(
            self.stable_sample_count,
            "active-view stable sample count",
        )
        max_center_deviation_m = _positive_float(
            self.max_center_deviation_m,
            "active-view center deviation limit",
        )
        max_axis_mad_m = _positive_float(
            self.max_axis_mad_m,
            "active-view MAD limit",
        )
        max_translation_m = _positive_float(
            self.max_translation_m,
            "active-view translation limit",
        )
        if max_translation_m > 0.020:
            raise InvalidDataError("active-view translation limit cannot exceed 20 mm")
        max_rotation_rad = _positive_float(
            self.max_rotation_rad,
            "active-view rotation limit",
        )
        if max_rotation_rad > float(np.deg2rad(5.0)) + 1e-12:
            raise InvalidDataError("active-view rotation limit cannot exceed 5 degrees")
        max_refinement_steps = _positive_int(
            self.max_refinement_steps,
            "active-view refinement limit",
        )
        if max_refinement_steps > 3:
            raise InvalidDataError("active-view refinement limit cannot exceed 3 steps")
        proposal_ttl_ns = _positive_int(
            self.proposal_ttl_ns,
            "active-view proposal TTL",
        )
        if proposal_ttl_ns > 1_000_000_000:
            raise InvalidDataError("active-view proposal TTL cannot exceed 1 second")
        poses = tuple(self.observation_poses)
        if any(not isinstance(pose, ObservationPose) for pose in poses):
            raise InvalidDataError("observation catalog contains an invalid pose")
        pose_ids = tuple(pose.pose_id for pose in poses)
        if len(set(pose_ids)) != len(pose_ids):
            raise InvalidDataError("observation catalog contains duplicate pose IDs")
        object.__setattr__(self, "inner_roi_fraction", inner_roi_fraction)
        object.__setattr__(self, "coverage_margin_m", coverage_margin_m)
        object.__setattr__(self, "min_depth_points", min_depth_points)
        object.__setattr__(self, "min_central_fraction", min_central_fraction)
        object.__setattr__(self, "stable_sample_count", stable_sample_count)
        object.__setattr__(self, "max_center_deviation_m", max_center_deviation_m)
        object.__setattr__(self, "max_axis_mad_m", max_axis_mad_m)
        object.__setattr__(self, "max_translation_m", max_translation_m)
        object.__setattr__(self, "max_rotation_rad", max_rotation_rad)
        object.__setattr__(self, "max_refinement_steps", max_refinement_steps)
        object.__setattr__(self, "proposal_ttl_ns", proposal_ttl_ns)
        object.__setattr__(self, "observation_poses", poses)


def load_active_view_config_dict(raw: Any) -> ActiveViewConfig:
    """Validate an untrusted mapping into an execution-locked config."""

    data = _mapping(raw, "active-view config")
    for key, value in data.items():
        if "execution_enabled" in str(key) and value is not False:
            raise InvalidDataError("active-view execution must remain disabled")
    _exact_keys(data, _TOP_LEVEL_KEYS, "active-view config")
    if data["schema_version"] != 1:
        raise InvalidDataError("unsupported active-view schema version")
    dry_run_enabled = _boolean(data["dry_run_enabled"], "dry_run_enabled")
    execution_enabled = _boolean(
        data["active_view_execution_enabled"],
        "active_view_execution_enabled",
    )
    if execution_enabled:
        raise InvalidDataError("active-view execution must remain disabled")

    table_raw = _mapping(data["table_plane"], "table_plane")
    _exact_keys(table_raw, _TABLE_KEYS, "table_plane")
    table = TablePlane(
        normal_base=table_raw["normal_base"],
        offset_m=_finite_float(table_raw["offset_m"], "table_plane.offset_m"),
        position_rmse_m=_positive_float(
            table_raw["position_rmse_m"],
            "table_plane.position_rmse_m",
        ),
        calibration_id=table_raw["calibration_id"],
        validated=_boolean(table_raw["validated"], "table_plane.validated"),
    )

    quality = _mapping(data["quality"], "quality")
    _exact_keys(quality, _QUALITY_KEYS, "quality")
    inner_roi_fraction = _fraction(
        quality["inner_roi_fraction"],
        "quality.inner_roi_fraction",
    )
    coverage_margin_m = _positive_float(
        quality["coverage_margin_m"],
        "quality.coverage_margin_m",
    )
    min_depth_points = _positive_int(
        quality["min_depth_points"],
        "quality.min_depth_points",
    )
    min_central_fraction = _fraction(
        quality["min_central_fraction"],
        "quality.min_central_fraction",
    )
    stable_sample_count = _positive_int(
        quality["stable_sample_count"],
        "quality.stable_sample_count",
    )
    max_center_deviation_m = _positive_float(
        quality["max_center_deviation_m"],
        "quality.max_center_deviation_m",
    )
    max_axis_mad_m = _positive_float(
        quality["max_axis_mad_m"],
        "quality.max_axis_mad_m",
    )

    motion = _mapping(data["motion_proposals"], "motion_proposals")
    _exact_keys(motion, _MOTION_KEYS, "motion_proposals")
    max_translation_m = _positive_float(
        motion["max_translation_m"],
        "motion_proposals.max_translation_m",
    )
    if max_translation_m > 0.020:
        raise InvalidDataError("active-view translation limit cannot exceed 20 mm")
    max_rotation_deg = _positive_float(
        motion["max_rotation_deg"],
        "motion_proposals.max_rotation_deg",
    )
    if max_rotation_deg > 5.0:
        raise InvalidDataError("active-view rotation limit cannot exceed 5 degrees")
    max_refinement_steps = _positive_int(
        motion["max_refinement_steps"],
        "motion_proposals.max_refinement_steps",
    )
    if max_refinement_steps > 3:
        raise InvalidDataError("active-view refinement limit cannot exceed 3 steps")
    proposal_ttl_ms = _positive_int(
        motion["proposal_ttl_ms"],
        "motion_proposals.proposal_ttl_ms",
    )
    if proposal_ttl_ms > 1_000:
        raise InvalidDataError("active-view proposal TTL cannot exceed 1 second")

    poses_raw = data["observation_poses"]
    if not isinstance(poses_raw, list):
        raise InvalidDataError("observation_poses must be a list")
    poses: list[ObservationPose] = []
    for index, item in enumerate(poses_raw):
        pose_raw = _mapping(item, f"observation_poses[{index}]")
        _exact_keys(
            pose_raw,
            _POSE_REQUIRED_KEYS,
            f"observation_poses[{index}]",
            _POSE_OPTIONAL_KEYS,
        )
        poses.append(
            ObservationPose(
                pose_id=pose_raw["pose_id"],
                joints_deg=pose_raw["joints_deg"],
                t_base_from_flange=pose_raw["t_base_from_flange"],
                coverage_polygon_xy_m=pose_raw["coverage_polygon_xy_m"],
                allowed_start_pose_ids=tuple(pose_raw["allowed_start_pose_ids"]),
                path_validation_id=pose_raw["path_validation_id"],
                calibration_id=pose_raw["calibration_id"],
                joint_tolerance_deg=pose_raw.get("joint_tolerance_deg", 1.0),
            )
        )

    return ActiveViewConfig(
        dry_run_enabled=dry_run_enabled,
        execution_enabled=False,
        table_plane=table,
        inner_roi_fraction=inner_roi_fraction,
        coverage_margin_m=coverage_margin_m,
        min_depth_points=min_depth_points,
        min_central_fraction=min_central_fraction,
        stable_sample_count=stable_sample_count,
        max_center_deviation_m=max_center_deviation_m,
        max_axis_mad_m=max_axis_mad_m,
        max_translation_m=max_translation_m,
        max_rotation_rad=float(np.deg2rad(max_rotation_deg)),
        max_refinement_steps=max_refinement_steps,
        proposal_ttl_ns=proposal_ttl_ms * 1_000_000,
        observation_poses=tuple(poses),
    )


def load_active_view_config(path: Path | str) -> ActiveViewConfig:
    """Load a YAML file without granting any execution capability."""

    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise InvalidDataError(f"invalid active-view YAML: {exc}") from exc
    return load_active_view_config_dict(raw)


__all__ = [
    "ActiveViewConfig",
    "load_active_view_config",
    "load_active_view_config_dict",
]
