"""Composition adapter from dual-camera fusion context to grasp previews."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml
from vision.active_view_types import TablePlane, validated_evidence_ids
from vision.d435_instance_verifier import D435InstanceVerification
from vision.dual_camera import (
    DualCameraCalibrationBundle,
    DualCameraFusionContext,
    DualCameraTarget,
)
from vision.grasp_geometry import (
    GraspGeometryConfig,
    GraspPreviewAccumulator,
    GraspPreviewStatus,
    evaluate_top_down_grasp,
)
from vision.types import InvalidDataError

from .contracts import InstanceDetection, ModelContractError


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelContractError(f"{name} must be an object")
    return value


def _exact(value: dict[str, Any], keys: set[str], name: str) -> None:
    if set(value) != keys:
        raise ModelContractError(f"{name} keys are invalid")


def load_grasp_preview_config(path: Path | str) -> GraspGeometryConfig:
    source = Path(path).resolve()
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ModelContractError(f"cannot read grasp preview config: {error}") from error
    raw = _mapping(raw, "grasp preview config")
    _exact(
        raw,
        {"schema_version", "depth", "object", "gripper", "motion", "workspace", "stability"},
        "grasp preview config",
    )
    if raw["schema_version"] != 1:
        raise ModelContractError("grasp preview schema_version must be 1")
    depth = _mapping(raw["depth"], "depth")
    object_limits = _mapping(raw["object"], "object")
    gripper = _mapping(raw["gripper"], "gripper")
    motion = _mapping(raw["motion"], "motion")
    workspace = _mapping(raw["workspace"], "workspace")
    stability = _mapping(raw["stability"], "stability")
    _exact(
        depth,
        {
            "min_points",
            "erosion_px",
            "mad_scale",
            "noise_floor_m",
            "inner_roi_fraction",
            "min_central_fraction",
            "max_axis_mad_m",
        },
        "depth",
    )
    _exact(object_limits, {"min_height_m", "max_height_m"}, "object")
    _exact(gripper, {"min_width_m", "max_width_m", "width_margin_m"}, "gripper")
    _exact(motion, {"pregrasp_clearance_m", "retreat_clearance_m"}, "motion")
    _exact(workspace, {"min_m", "max_m"}, "workspace")
    _exact(
        stability,
        {"sample_count", "max_center_deviation_m", "max_axis_mad_m"},
        "stability",
    )
    return GraspGeometryConfig(
        min_points=depth["min_points"],
        erosion_px=depth["erosion_px"],
        mad_scale=depth["mad_scale"],
        noise_floor_m=depth["noise_floor_m"],
        inner_roi_fraction=depth["inner_roi_fraction"],
        min_central_fraction=depth["min_central_fraction"],
        max_axis_mad_m=depth["max_axis_mad_m"],
        min_object_height_m=object_limits["min_height_m"],
        max_object_height_m=object_limits["max_height_m"],
        min_gripper_width_m=gripper["min_width_m"],
        max_gripper_width_m=gripper["max_width_m"],
        grasp_width_margin_m=gripper["width_margin_m"],
        pregrasp_clearance_m=motion["pregrasp_clearance_m"],
        retreat_clearance_m=motion["retreat_clearance_m"],
        workspace_min_m=workspace["min_m"],
        workspace_max_m=workspace["max_m"],
        stable_sample_count=stability["sample_count"],
        max_center_deviation_m=stability["max_center_deviation_m"],
        max_temporal_axis_mad_m=stability["max_axis_mad_m"],
    )


class OnlineGraspPreviewAdapter:
    """Own temporal preview state without owning any execution transport."""

    def __init__(
        self,
        *,
        table: TablePlane,
        config: GraspGeometryConfig,
        foundation_evidence_ids: tuple[str, ...],
    ) -> None:
        if not isinstance(table, TablePlane) or not table.validated:
            raise ModelContractError("grasp preview requires a validated table")
        if not isinstance(config, GraspGeometryConfig):
            raise ModelContractError("grasp preview requires geometry config")
        self.table = table
        self.config = config
        self.foundation_evidence_ids = validated_evidence_ids(foundation_evidence_ids)
        self._accumulators: dict[int, GraspPreviewAccumulator] = {}

    def _reset(self) -> None:
        self._accumulators.clear()

    def evaluate(
        self,
        *,
        detections: Any,
        targets: Any,
        fusion_context: DualCameraFusionContext | None,
        calibration: DualCameraCalibrationBundle | None,
        robot_pose: Any,
        arm_stationary: bool,
        now_ns: int,
        d435_verifications: Mapping[int, D435InstanceVerification] | None = None,
    ) -> tuple[GraspPreviewStatus, ...]:
        del robot_pose
        detection_items = tuple(detections)
        target_items = tuple(targets)
        if not all(isinstance(item, InstanceDetection) for item in detection_items):
            raise ModelContractError("grasp preview detections are invalid")
        if not all(isinstance(item, DualCameraTarget) for item in target_items):
            raise ModelContractError("grasp preview targets are invalid")
        if not isinstance(arm_stationary, bool):
            raise ModelContractError("grasp preview stationarity must be explicit")
        if fusion_context is None or calibration is None or not arm_stationary:
            self._reset()
            return ()
        if not isinstance(fusion_context, DualCameraFusionContext) or not isinstance(
            calibration, DualCameraCalibrationBundle
        ):
            raise ModelContractError("grasp preview fusion evidence is invalid")
        if now_ns < fusion_context.source_stamp.monotonic_ns:
            raise ModelContractError("grasp preview time precedes fusion evidence")
        if fusion_context.calibration_id != calibration.calibration.calibration_id:
            self._reset()
            return ()
        detections_by_id = {item.detection_id: item for item in detection_items}
        if len(detections_by_id) != len(detection_items):
            raise ModelContractError("grasp preview detection IDs must be unique")
        evidence_ids = tuple(
            dict.fromkeys(
                (*fusion_context.evidence_ids, *self.foundation_evidence_ids)
            )
        )
        validated_evidence_ids(evidence_ids)
        active_identities: set[int] = set()
        statuses: list[GraspPreviewStatus] = []
        for target in target_items:
            if target.identity_id is None:
                continue
            detection = detections_by_id.get(target.detection_id)
            if detection is None:
                raise ModelContractError("grasp target lacks its source detection")
            identity_id = int(target.identity_id)
            verification = (
                None
                if d435_verifications is None
                else d435_verifications.get(target.detection_id)
            )
            if d435_verifications is not None and (
                verification is None or not verification.verified
            ):
                continue
            active_identities.add(identity_id)
            accumulator = self._accumulators.setdefault(
                identity_id,
                GraspPreviewAccumulator(self.config),
            )
            try:
                evaluation = evaluate_top_down_grasp(
                    identity_id=identity_id,
                    detection_id=target.detection_id,
                    registered=fusion_context.registered,
                    target_mask=detection.mask,
                    d435=calibration.d435,
                    t_d435_from_lumos=fusion_context.t_d435_from_lumos,
                    t_base_from_lumos=fusion_context.t_base_from_lumos,
                    table=self.table,
                    source_stamp=fusion_context.source_stamp,
                    calibration_id=fusion_context.calibration_id,
                    evidence_ids=evidence_ids,
                    config=self.config,
                    d435_instance_mask=(
                        None if verification is None else verification.d435_mask
                    ),
                )
            except InvalidDataError as error:
                raise ModelContractError(f"invalid grasp geometry: {error}") from error
            status = accumulator.update(evaluation)
            if status.candidate is None:
                continue
            if not target.actionable or target.reasons:
                status = status.with_blockers(
                    *(target.reasons or ("target_not_actionable",))
                )
            statuses.append(status)
        for identity_id in tuple(self._accumulators):
            if identity_id not in active_identities:
                self._accumulators.pop(identity_id, None)
        return tuple(statuses[:256])


__all__ = ["OnlineGraspPreviewAdapter", "load_grasp_preview_config"]
