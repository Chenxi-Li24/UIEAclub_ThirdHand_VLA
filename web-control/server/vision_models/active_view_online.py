"""Strict configuration boundary for hardware-independent active-view planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import yaml

from vision.active_view_geometry import estimate_table_target
from vision.active_view_planner import select_observation_pose
from vision.active_view_types import (
    ObservationMoveProposal,
    ObservationPose,
    TablePlane,
)
from vision.dual_camera import (
    DualCameraCalibrationBundle,
    DualCameraTarget,
    StampedRobotPose,
)
from vision.geometry import validate_transform
from vision.types import FrameStamp, InvalidDataError

from .contracts import InstanceDetection


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


@dataclass(frozen=True)
class ActiveViewTargetReport:
    """Bounded presentation record; intentionally excludes all motion payloads."""

    detection_id: int
    identity_id: Optional[int]
    kind: str
    target_pose_id: Optional[str]
    expires_ns: Optional[int]
    coarse_center_xy_m: Optional[np.ndarray] = field(compare=False)
    valid_depth_points: int
    central_fraction: Optional[float]
    depth_acceptable: Optional[bool]
    reasons: tuple[str, ...]
    stable_samples: int = 0
    remaining_refinements: int = 0
    active_view_execution_enabled: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.detection_id, bool) or not isinstance(self.detection_id, int):
            raise InvalidDataError("active-view report detection_id must be non-negative")
        if self.detection_id < 0:
            raise InvalidDataError("active-view report detection_id must be non-negative")
        if self.identity_id is not None and (
            isinstance(self.identity_id, bool)
            or not isinstance(self.identity_id, int)
            or self.identity_id < 0
        ):
            raise InvalidDataError("active-view report identity_id must be non-negative")
        if self.kind not in {"none", "coarse_pose", "refine_delta"}:
            raise InvalidDataError("active-view report kind is invalid")
        if self.target_pose_id is not None and (
            not isinstance(self.target_pose_id, str) or not self.target_pose_id
        ):
            raise InvalidDataError("active-view report target pose ID is invalid")
        if self.expires_ns is not None and (
            isinstance(self.expires_ns, bool)
            or not isinstance(self.expires_ns, int)
            or self.expires_ns < 0
        ):
            raise InvalidDataError("active-view report expiry is invalid")
        if self.coarse_center_xy_m is None:
            center = None
        else:
            center = np.array(self.coarse_center_xy_m, dtype=float, copy=True)
            if center.shape != (2,) or not np.isfinite(center).all():
                raise InvalidDataError("active-view coarse center must be a finite XY vector")
            center.setflags(write=False)
        if (
            isinstance(self.valid_depth_points, bool)
            or not isinstance(self.valid_depth_points, int)
            or self.valid_depth_points < 0
        ):
            raise InvalidDataError("active-view valid depth count is invalid")
        if self.central_fraction is not None:
            fraction = float(self.central_fraction)
            if not np.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
                raise InvalidDataError("active-view central fraction must be within [0, 1]")
        else:
            fraction = None
        if self.depth_acceptable is not None and not isinstance(self.depth_acceptable, bool):
            raise InvalidDataError("active-view depth quality state must be a boolean or null")
        counters = (self.stable_samples, self.remaining_refinements)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counters
        ):
            raise InvalidDataError("active-view report counters must be non-negative integers")
        if self.remaining_refinements > 3:
            raise InvalidDataError("active-view report refinements cannot exceed three")
        reasons = tuple(self.reasons)
        if any(
            not isinstance(reason, str) or not reason or len(reason) > 128
            for reason in reasons
        ):
            raise InvalidDataError("active-view report reasons must be bounded strings")
        if self.active_view_execution_enabled is not False:
            raise InvalidDataError("active-view report execution must remain disabled")
        object.__setattr__(self, "coarse_center_xy_m", center)
        object.__setattr__(self, "central_fraction", fraction)
        object.__setattr__(self, "reasons", reasons[:32])

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_view_execution_enabled": False,
            "central_fraction": self.central_fraction,
            "coarse_center_xy_m": (
                None
                if self.coarse_center_xy_m is None
                else self.coarse_center_xy_m.tolist()
            ),
            "depth_acceptable": self.depth_acceptable,
            "detection_id": self.detection_id,
            "expires_ns": self.expires_ns,
            "identity_id": self.identity_id,
            "kind": self.kind,
            "reasons": list(self.reasons),
            "remaining_refinements": self.remaining_refinements,
            "stable_samples": self.stable_samples,
            "target_pose_id": self.target_pose_id,
            "valid_depth_points": self.valid_depth_points,
        }


@dataclass(frozen=True)
class ActiveViewEvaluationBatch:
    """Separate presentation reports from trusted in-process motion proposals."""

    reports: tuple[ActiveViewTargetReport, ...]
    proposals: tuple[ObservationMoveProposal, ...]

    def __post_init__(self) -> None:
        reports = tuple(self.reports)
        proposals = tuple(self.proposals)
        if len(reports) > 256 or any(
            not isinstance(report, ActiveViewTargetReport) for report in reports
        ):
            raise InvalidDataError("active-view report batch is invalid or unbounded")
        if len(proposals) > len(reports) or any(
            not isinstance(proposal, ObservationMoveProposal) for proposal in proposals
        ):
            raise InvalidDataError("active-view proposal batch is invalid or unbounded")
        object.__setattr__(self, "reports", reports)
        object.__setattr__(self, "proposals", proposals)


class ActiveViewDryRunAdapter:
    """Adapt online perception outputs into non-executing active-view reports."""

    max_reports = 256
    max_frame_age_ns = 200_000_000

    def __init__(self, config: ActiveViewConfig) -> None:
        if not isinstance(config, ActiveViewConfig):
            raise InvalidDataError("active-view adapter requires ActiveViewConfig")
        self.config = config

    def evaluate(
        self,
        *,
        detections: Any,
        targets: Any,
        rgb_stamp: FrameStamp,
        robot_pose: Optional[StampedRobotPose],
        calibration: Optional[DualCameraCalibrationBundle],
        arm_stationary: bool,
        now_ns: int,
    ) -> tuple[ActiveViewTargetReport, ...]:
        return self.evaluate_with_proposals(
            detections=detections,
            targets=targets,
            rgb_stamp=rgb_stamp,
            robot_pose=robot_pose,
            calibration=calibration,
            arm_stationary=arm_stationary,
            current_joints_deg=None,
            now_ns=now_ns,
        ).reports

    def evaluate_with_proposals(
        self,
        *,
        detections: Any,
        targets: Any,
        rgb_stamp: FrameStamp,
        robot_pose: Optional[StampedRobotPose],
        calibration: Optional[DualCameraCalibrationBundle],
        arm_stationary: bool,
        current_joints_deg: Any,
        now_ns: int,
    ) -> ActiveViewEvaluationBatch:
        detection_items = tuple(detections)
        target_items = tuple(targets)
        if any(not isinstance(item, InstanceDetection) for item in detection_items):
            raise InvalidDataError("active-view adapter received an invalid detection")
        if any(not isinstance(item, DualCameraTarget) for item in target_items):
            raise InvalidDataError("active-view adapter received an invalid target")
        if not isinstance(rgb_stamp, FrameStamp):
            raise InvalidDataError("active-view adapter requires RGB frame provenance")
        if not isinstance(arm_stationary, bool):
            raise InvalidDataError("active-view arm state must be a boolean")
        if (
            isinstance(now_ns, bool)
            or not isinstance(now_ns, int)
            or now_ns < rgb_stamp.monotonic_ns
        ):
            raise InvalidDataError("active-view adapter time is invalid")
        if robot_pose is not None and not isinstance(robot_pose, StampedRobotPose):
            raise InvalidDataError("active-view adapter robot pose is invalid")
        if calibration is not None and not isinstance(calibration, DualCameraCalibrationBundle):
            raise InvalidDataError("active-view adapter calibration is invalid")

        target_by_detection: dict[int, DualCameraTarget] = {}
        for target in target_items:
            if target.detection_id in target_by_detection:
                raise InvalidDataError("active-view targets contain duplicate detection IDs")
            target_by_detection[target.detection_id] = target

        common_reasons: list[str] = []
        if not self.config.dry_run_enabled:
            common_reasons.append("active_view_dry_run_disabled")
        if not self.config.table_plane.validated:
            common_reasons.append("table_unvalidated")
        if not self.config.observation_poses:
            common_reasons.append("observation_catalog_empty")
        if calibration is None:
            common_reasons.append("calibration_unavailable")
        elif not calibration.calibration.validated:
            common_reasons.append("calibration_not_validated")
        if robot_pose is None:
            common_reasons.append("robot_pose_unavailable")
        if not arm_stationary:
            common_reasons.append("arm_not_stationary")
        if now_ns - rgb_stamp.monotonic_ns > self.max_frame_age_ns:
            common_reasons.append("camera_frames_stale")

        reports: list[ActiveViewTargetReport] = []
        proposals: list[ObservationMoveProposal] = []
        for detection in detection_items[: self.max_reports]:
            target = target_by_detection.get(detection.detection_id)
            if target is None:
                reports.append(
                    self._blocked_report(
                        detection.detection_id,
                        None,
                        ("target_result_missing",),
                    )
                )
                continue
            reasons = list(common_reasons)
            report_kind = "none"
            target_pose_id = None
            expires_ns = None
            if target.identity_id is None:
                reasons.append("identity_unavailable")
            coarse_center = None
            geometry_ready = not any(
                reason
                in {
                    "active_view_dry_run_disabled",
                    "table_unvalidated",
                    "calibration_unavailable",
                    "calibration_not_validated",
                    "robot_pose_unavailable",
                    "arm_not_stationary",
                    "camera_frames_stale",
                    "identity_unavailable",
                }
                for reason in reasons
            )
            if geometry_ready:
                assert calibration is not None
                assert robot_pose is not None
                assert target.identity_id is not None
                try:
                    calibration.verify_integrity()
                    t_base_from_lumos = validate_transform(
                        robot_pose.t_base_from_flange @ calibration.t_flange_from_lumos
                    )
                    estimate = estimate_table_target(
                        target.identity_id,
                        detection.mask,
                        calibration.lumos,
                        t_base_from_lumos,
                        self.config.table_plane,
                        rgb_stamp,
                    )
                    coarse_center = estimate.center_xy_m
                    if self.config.observation_poses:
                        if current_joints_deg is None:
                            reasons.append("current_joints_unavailable")
                        else:
                            proposal = select_observation_pose(
                                estimate=estimate,
                                poses=self.config.observation_poses,
                                current_joints_deg=current_joints_deg,
                                required_calibration_id=calibration.calibration.calibration_id,
                                now_ns=now_ns,
                                config=self.config,
                            )
                            if proposal.kind == "none":
                                reasons.extend(proposal.reasons)
                            else:
                                proposals.append(proposal)
                                report_kind = proposal.kind
                                target_pose_id = proposal.target_pose_id
                                expires_ns = proposal.expires_ns
                except InvalidDataError:
                    reasons.append("coarse_geometry_unavailable")
            depth_acceptable = bool(
                target.pose is not None
                and target.registered_depth_points >= self.config.min_depth_points
            )
            reports.append(
                ActiveViewTargetReport(
                    detection_id=detection.detection_id,
                    identity_id=target.identity_id,
                    kind=report_kind,
                    target_pose_id=target_pose_id,
                    expires_ns=expires_ns,
                    coarse_center_xy_m=coarse_center,
                    valid_depth_points=target.registered_depth_points,
                    central_fraction=None,
                    depth_acceptable=depth_acceptable,
                    reasons=tuple(dict.fromkeys(reasons)),
                    stable_samples=0,
                    remaining_refinements=self.config.max_refinement_steps,
                    active_view_execution_enabled=False,
                )
            )
        return ActiveViewEvaluationBatch(tuple(reports), tuple(proposals))

    def _blocked_report(
        self,
        detection_id: int,
        identity_id: Optional[int],
        reasons: tuple[str, ...],
    ) -> ActiveViewTargetReport:
        return ActiveViewTargetReport(
            detection_id=detection_id,
            identity_id=identity_id,
            kind="none",
            target_pose_id=None,
            expires_ns=None,
            coarse_center_xy_m=None,
            valid_depth_points=0,
            central_fraction=None,
            depth_acceptable=None,
            reasons=reasons,
            stable_samples=0,
            remaining_refinements=self.config.max_refinement_steps,
            active_view_execution_enabled=False,
        )


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
    "ActiveViewDryRunAdapter",
    "ActiveViewTargetReport",
    "load_active_view_config",
    "load_active_view_config_dict",
]
