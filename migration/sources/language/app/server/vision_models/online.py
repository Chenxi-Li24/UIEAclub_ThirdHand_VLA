"""Hardware-independent, fail-closed online REMIND perception orchestration."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import re
import time
from typing import Any, Optional

import numpy as np
import yaml

from vision.active_view_types import ObservationMoveProposal
from vision.dual_camera import (
    DualCameraConfig,
    DualCameraCalibrationBundle,
    DualCameraPerception,
    DualCameraTarget,
    StampedRobotPose,
)
from vision.identity import PersistentIdentityConfig
from vision.grasp_geometry import GraspPreviewStatus
from vision.d435_instance_verifier import D435InstanceVerification
from vision.instance_pose import InstancePoseConfig
from vision.online_frames import CameraRoleMap, FramePair
from vision.types import InvalidDataError
from vision.model_acceptance import ModelAcceptanceError, validate_task_checkpoint

from .contracts import InstanceDetection, ModelContractError, validated_rgb_image
from .active_view_online import (
    ActiveViewEvaluationBatch,
    ActiveViewTargetObservation,
    ActiveViewTargetReport,
)
from .offline_replay import IdentityReplayFormatError
from .visualization import build_target_visuals, render_target_visuals


COCO_INSTANCE_LABELS = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
    "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
)


@dataclass(frozen=True)
class OnlineVisionConfig:
    roles: CameraRoleMap
    detector_backend: str
    detector_config_path: Optional[Path]
    detector_checkpoint_path: Optional[Path]
    detector_labels: tuple[str, ...]
    descriptor_model_id: str
    detector_device: str
    descriptor_device: str
    detector_min_score: float
    dino_max_long_side: int
    min_patch_coverage: float
    task_checkpoint_validated: bool
    accepted_task_labels: tuple[str, ...]
    latest_only: bool
    max_pending_frames: int
    max_targets_per_frame: int
    latency_p95_limit_ms: float
    gpu_memory_limit_gib: float
    robot_execution_enabled: bool
    identity_config: PersistentIdentityConfig
    perception_config: DualCameraConfig

    def __post_init__(self) -> None:
        if not isinstance(self.roles, CameraRoleMap):
            raise ModelContractError("online config requires explicit camera roles")
        if not isinstance(self.identity_config, PersistentIdentityConfig):
            raise ModelContractError("online config requires persistent identity settings")
        if not isinstance(self.perception_config, DualCameraConfig):
            raise ModelContractError("online config requires dual-camera perception settings")
        if self.perception_config.roles != self.roles:
            raise ModelContractError("online and perception camera roles must match")
        identifiers = (
            self.detector_backend,
            self.descriptor_model_id,
            self.detector_device,
            self.descriptor_device,
        )
        if any(not isinstance(value, str) or not value for value in identifiers):
            raise ModelContractError("online model identifiers must be non-empty strings")
        if not self.detector_labels or not all(
            isinstance(label, str) and label for label in self.detector_labels
        ):
            raise ModelContractError("detector labels must be non-empty strings")
        for path in (self.detector_config_path, self.detector_checkpoint_path):
            if path is not None and not isinstance(path, Path):
                raise ModelContractError("model paths must be pathlib Paths or None")
        if not re.fullmatch(r"cuda:\d+", self.detector_device) or not re.fullmatch(
            r"cuda:\d+", self.descriptor_device
        ):
            raise ModelContractError("online models require explicit CUDA devices")
        probabilities = (self.detector_min_score, self.min_patch_coverage)
        if not np.isfinite(probabilities).all() or any(
            not 0.0 <= value <= 1.0 for value in probabilities
        ):
            raise ModelContractError("online probability thresholds must be within [0, 1]")
        integer_limits = (
            self.dino_max_long_side,
            self.max_pending_frames,
            self.max_targets_per_frame,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in integer_limits
        ):
            raise ModelContractError("online integer limits must be positive integers")
        if not self.latest_only or self.max_pending_frames != 1:
            raise ModelContractError("online scheduling must be latest-only with capacity one")
        if not np.isfinite(
            [self.latency_p95_limit_ms, self.gpu_memory_limit_gib]
        ).all() or min(self.latency_p95_limit_ms, self.gpu_memory_limit_gib) <= 0.0:
            raise ModelContractError("online latency and GPU limits must be finite and positive")
        if self.robot_execution_enabled is not False:
            raise ModelContractError("robot execution must remain disabled")
        if not isinstance(self.task_checkpoint_validated, bool):
            raise ModelContractError("task checkpoint validation must be an explicit boolean")
        if (
            not isinstance(self.accepted_task_labels, tuple)
            or any(not isinstance(label, str) or not label for label in self.accepted_task_labels)
            or len(set(self.accepted_task_labels)) != len(self.accepted_task_labels)
        ):
            raise ModelContractError("accepted task labels must be unique non-empty strings")
        if self.task_checkpoint_validated != bool(self.accepted_task_labels):
            raise ModelContractError(
                "validated task checkpoints require a non-empty accepted label scope"
            )


@dataclass(frozen=True)
class OnlineAnnotation:
    detection_id: int
    label: str
    score: float
    bbox_xyxy: np.ndarray
    mask: np.ndarray = field(compare=False)

    def __post_init__(self) -> None:
        box = np.array(self.bbox_xyxy, dtype=float, copy=True)
        if box.shape != (4,) or not np.isfinite(box).all():
            raise ModelContractError("overlay bounding box must be a finite four-vector")
        mask = np.asarray(self.mask)
        if mask.ndim != 2 or mask.dtype != np.bool_ or not mask.any():
            raise ModelContractError("overlay mask must be a non-empty 2D boolean array")
        box.setflags(write=False)
        mask = np.array(mask, copy=True)
        mask.setflags(write=False)
        object.__setattr__(self, "bbox_xyxy", box)
        object.__setattr__(self, "mask", mask)


def _target_event(target: DualCameraTarget) -> dict[str, Any]:
    pose = target.pose
    return {
        "actionable": bool(target.actionable),
        "detection_id": int(target.detection_id),
        "identity_id": None if target.identity_id is None else int(target.identity_id),
        "identity_status": target.identity_status.value,
        "identity_memory": {
            "hits": int(target.identity_hits),
            "work_prototype_count": int(target.work_prototype_count),
            "stable_prototype_count": int(target.stable_prototype_count),
            "appearance_similarity": target.appearance_similarity,
            "association_cost": target.association_cost,
            "association_reason": target.association_reason,
        },
        "label": target.label,
        "d435_same_instance": None
        if target.d435_verification is None
        else target.d435_verification.to_dict(),
        "grasp_preview": None
        if target.grasp_preview is None
        else target.grasp_preview.to_dict(),
        "pose": None
        if pose is None
        else {
            "calibration_id": pose.calibration_id,
            "covariance_m2": pose.covariance_m2.tolist(),
            "frame": pose.frame,
            "monotonic_ns": int(pose.stamp.monotonic_ns),
            "xyz_m": pose.xyz_m.tolist(),
        },
        "reasons": list(target.reasons),
        "registered_depth_points": int(target.registered_depth_points),
        "score": float(target.score),
    }


@dataclass(frozen=True)
class OnlinePerceptionResult:
    frame_id: int
    monotonic_ns: int
    event_ts_ms: int
    canonical_rgb_source: str
    metric_depth_source: str
    targets: tuple[DualCameraTarget, ...]
    annotations: tuple[OnlineAnnotation, ...]
    latency_ms: float
    latency_p95_ms: float
    gpu_memory_reserved_gib: Optional[float]
    model_ready: bool
    task_checkpoint_validated: bool
    robot_execution_enabled: bool
    blockers: tuple[str, ...]
    active_view_reports: tuple[ActiveViewTargetReport, ...]
    active_view_proposals: tuple[ObservationMoveProposal, ...]
    active_view_observations: tuple[ActiveViewTargetObservation, ...]
    model_error: Optional[str] = None

    def to_event(self) -> dict[str, Any]:
        payload = {
            "blockers": list(self.blockers),
            "active_view_reports": [report.to_dict() for report in self.active_view_reports],
            "canonical_rgb_source": self.canonical_rgb_source,
            "frame_id": int(self.frame_id),
            "gpu_memory_reserved_gib": self.gpu_memory_reserved_gib,
            "latency_ms": float(self.latency_ms),
            "latency_p95_ms": float(self.latency_p95_ms),
            "metric_depth_source": self.metric_depth_source,
            "model_error": self.model_error,
            "model_ready": bool(self.model_ready),
            "monotonic_ns": int(self.monotonic_ns),
            "robot_execution_enabled": False,
            "source_sequence": int(self.frame_id),
            "targets": [_target_event(target) for target in self.targets],
            "task_checkpoint_validated": bool(self.task_checkpoint_validated),
            "ts": int(self.event_ts_ms),
            "type": "detection_result",
        }
        # Enforce the process boundary contract here, before Node sees the event.
        json.dumps(payload, allow_nan=False)
        return payload


def _visibility(detection: InstanceDetection) -> float:
    x1, y1, x2, y2 = detection.bbox_xyxy
    bbox_area = max(float((x2 - x1) * (y2 - y1)), 1.0)
    return float(np.clip(np.count_nonzero(detection.mask) / bbox_area, 0.0, 1.0))


def _cuda_reserved_gib() -> Optional[float]:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        value = float(torch.cuda.memory_reserved()) / float(1024**3)
        return value if np.isfinite(value) else None
    except (ImportError, RuntimeError, TypeError, ValueError):
        return None


class OnlinePerceptionEngine:
    """Run one latest Lumos frame through segmentation, DINO, and fusion."""

    def __init__(
        self,
        segmenter,
        encoder,
        perception,
        config: OnlineVisionConfig,
        *,
        active_view=None,
        grasp_preview=None,
        d435_instance_verifier=None,
    ) -> None:
        if not callable(getattr(segmenter, "predict", None)):
            raise ModelContractError("segmenter must expose predict(image_rgb)")
        if not callable(getattr(encoder, "encode", None)):
            raise ModelContractError("encoder must expose encode(image_rgb, masks)")
        if not isinstance(perception, DualCameraPerception):
            raise ModelContractError("perception must be a DualCameraPerception")
        if not isinstance(config, OnlineVisionConfig):
            raise ModelContractError("config must be an OnlineVisionConfig")
        if perception.config.roles != config.roles:
            raise ModelContractError("engine and fusion camera roles must match")
        if active_view is not None and not callable(getattr(active_view, "evaluate", None)):
            raise ModelContractError("active-view adapter must expose evaluate()")
        if grasp_preview is not None and not callable(getattr(grasp_preview, "evaluate", None)):
            raise ModelContractError("grasp-preview adapter must expose evaluate()")
        if d435_instance_verifier is not None and not callable(
            getattr(d435_instance_verifier, "evaluate", None)
        ):
            raise ModelContractError("D435 instance adapter must expose evaluate()")
        self.segmenter = segmenter
        self.encoder = encoder
        self.perception = perception
        self.config = config
        self.active_view = active_view
        self.grasp_preview = grasp_preview
        self.d435_instance_verifier = d435_instance_verifier
        self._latencies_ms: deque[float] = deque(maxlen=256)

    @property
    def latency_sample_count(self) -> int:
        return len(self._latencies_ms)

    def _finish(
        self,
        *,
        pair: FramePair,
        started_ns: int,
        targets: tuple[DualCameraTarget, ...],
        annotations: tuple[OnlineAnnotation, ...],
        model_ready: bool,
        blockers: tuple[str, ...],
        active_view_reports: tuple[ActiveViewTargetReport, ...] = (),
        active_view_proposals: tuple[ObservationMoveProposal, ...] = (),
        active_view_observations: tuple[ActiveViewTargetObservation, ...] = (),
        model_error: Optional[str] = None,
    ) -> OnlinePerceptionResult:
        latency_ms = max(0.0, (time.perf_counter_ns() - started_ns) / 1_000_000.0)
        self._latencies_ms.append(latency_ms)
        latency_p95_ms = float(np.percentile(tuple(self._latencies_ms), 95))
        memory = _cuda_reserved_gib()
        combined = list(blockers)
        if latency_p95_ms > self.config.latency_p95_limit_ms:
            combined.append("latency_budget_exceeded")
        if memory is not None and memory > self.config.gpu_memory_limit_gib:
            combined.append("gpu_memory_budget_exceeded")
        combined = list(dict.fromkeys(combined))
        return OnlinePerceptionResult(
            frame_id=pair.rgb.stamp.frame_id,
            monotonic_ns=pair.fusion_monotonic_ns,
            event_ts_ms=int(time.time() * 1000),
            canonical_rgb_source=self.config.roles.canonical_rgb_source,
            metric_depth_source=self.config.roles.metric_depth_source,
            targets=targets,
            annotations=annotations,
            latency_ms=latency_ms,
            latency_p95_ms=latency_p95_ms,
            gpu_memory_reserved_gib=memory,
            model_ready=model_ready,
            task_checkpoint_validated=self.config.task_checkpoint_validated,
            robot_execution_enabled=False,
            blockers=tuple(combined),
            active_view_reports=active_view_reports,
            active_view_proposals=active_view_proposals,
            active_view_observations=active_view_observations,
            model_error=model_error,
        )

    def process(
        self,
        pair: FramePair,
        robot_pose: Optional[StampedRobotPose],
        calibration: Optional[DualCameraCalibrationBundle],
        arm_stationary: bool,
        now_ns: int,
        current_joints_deg: Any = None,
        refinement_evidence_ids: Any = (),
    ) -> OnlinePerceptionResult:
        started_ns = time.perf_counter_ns()
        if not isinstance(pair, FramePair):
            raise ModelContractError("online processing requires a FramePair")
        if pair.rgb.stamp.source != self.config.roles.canonical_rgb_source:
            raise ModelContractError("online frame does not match the canonical RGB role")
        annotations: tuple[OnlineAnnotation, ...] = ()
        try:
            detections = tuple(self.segmenter.predict(pair.rgb.image_rgb))[
                : self.config.max_targets_per_frame
            ]
            if not all(isinstance(item, InstanceDetection) for item in detections):
                raise ModelContractError("segmenter returned a non-detection value")
            annotations = tuple(
                OnlineAnnotation(
                    item.detection_id,
                    item.label,
                    item.score,
                    item.bbox_xyxy,
                    item.mask,
                )
                for item in detections
            )
            descriptors = (
                tuple(self.encoder.encode(pair.rgb.image_rgb, (item.mask for item in detections)))
                if detections
                else ()
            )
            result = self.perception.process(
                rgb_stamp=pair.rgb.stamp,
                depth_stamp=None if pair.depth is None else pair.depth.stamp,
                robot_pose=robot_pose,
                detections=detections,
                descriptors=descriptors,
                visibilities=tuple(_visibility(item) for item in detections),
                depth_z_m=None if pair.depth is None else pair.depth.depth_z_m,
                calibration=calibration,
                arm_stationary=arm_stationary,
                now_ns=now_ns,
            )
            targets = result.targets
            d435_verifications: dict[int, D435InstanceVerification] = {}
            if self.d435_instance_verifier is not None:
                unavailable_reason = None
                candidate_verifications: tuple[D435InstanceVerification, ...] = ()
                if pair.debug_rgb is None:
                    unavailable_reason = "d435_rgb_unavailable"
                elif result.fusion_context is None or calibration is None:
                    unavailable_reason = "d435_fusion_unavailable"
                else:
                    try:
                        candidate_verifications = tuple(
                            self.d435_instance_verifier.evaluate(
                                d435_rgb=pair.debug_rgb,
                                lumos_detections=detections,
                                fusion_context=result.fusion_context,
                                calibration=calibration,
                            )
                        )
                        if any(
                            not isinstance(item, D435InstanceVerification)
                            for item in candidate_verifications
                        ):
                            raise ModelContractError(
                                "D435 instance adapter returned invalid evidence"
                            )
                    except Exception as verification_error:
                        if isinstance(verification_error, (KeyboardInterrupt, SystemExit)):
                            raise
                        unavailable_reason = "d435_instance_verifier_unavailable"
                if unavailable_reason is not None:
                    candidate_verifications = tuple(
                        D435InstanceVerification(
                            lumos_detection_id=detection.detection_id,
                            d435_detection_id=None,
                            label=detection.label,
                            verified=False,
                            projected_points=0,
                            support_points=0,
                            support_fraction=0.0,
                            d435_bbox_xyxy=None,
                            d435_mask=None,
                            blockers=(unavailable_reason,),
                        )
                        for detection in detections
                    )
                d435_verifications = {
                    item.lumos_detection_id: item for item in candidate_verifications
                }
                if len(d435_verifications) != len(detections):
                    raise ModelContractError(
                        "D435 verification must cover every Lumos detection exactly once"
                    )
                targets = tuple(
                    replace(
                        target,
                        actionable=bool(
                            target.actionable
                            and d435_verifications[target.detection_id].verified
                        ),
                        reasons=tuple(
                            dict.fromkeys(
                                (
                                    *target.reasons,
                                    *d435_verifications[target.detection_id].blockers,
                                )
                            )
                        ),
                        d435_verification=d435_verifications[target.detection_id],
                    )
                    for target in targets
                )
            if self.grasp_preview is not None:
                try:
                    previews = tuple(
                        self.grasp_preview.evaluate(
                            detections=detections,
                            targets=targets,
                            fusion_context=result.fusion_context,
                            calibration=calibration,
                            robot_pose=robot_pose,
                            arm_stationary=arm_stationary,
                            now_ns=now_ns,
                            d435_verifications=d435_verifications,
                        )
                    )
                    if any(not isinstance(item, GraspPreviewStatus) for item in previews):
                        raise ModelContractError(
                            "grasp-preview adapter returned an invalid status"
                        )
                    by_detection = {
                        item.candidate.detection_id: item
                        for item in previews
                        if item.candidate is not None
                    }
                    if len(by_detection) != sum(
                        item.candidate is not None for item in previews
                    ):
                        raise ModelContractError("grasp-preview detection IDs must be unique")
                    targets = tuple(
                        replace(
                            target,
                            grasp_preview=by_detection.get(target.detection_id),
                        )
                        for target in targets
                    )
                except Exception as grasp_error:
                    if isinstance(grasp_error, (KeyboardInterrupt, SystemExit)):
                        raise
                    targets = tuple(
                        replace(
                            target,
                            reasons=tuple(
                                dict.fromkeys(
                                    (*target.reasons, "grasp_preview_adapter_unavailable")
                                )
                            ),
                        )
                        for target in targets
                    )
            if not self.config.task_checkpoint_validated:
                targets = tuple(
                    replace(
                        target,
                        actionable=False,
                        reasons=tuple(
                            dict.fromkeys((*target.reasons, "task_checkpoint_unvalidated"))
                        ),
                        grasp_preview=None
                        if target.grasp_preview is None
                        else target.grasp_preview.with_blockers(
                            *target.reasons,
                            "task_checkpoint_unvalidated",
                        ),
                    )
                    for target in targets
                )
            else:
                accepted_labels = set(self.config.accepted_task_labels)
                targets = tuple(
                    target
                    if target.label in accepted_labels
                    else replace(
                        target,
                        actionable=False,
                        reasons=tuple(
                            dict.fromkeys((*target.reasons, "task_checkpoint_unvalidated"))
                        ),
                        grasp_preview=None
                        if target.grasp_preview is None
                        else target.grasp_preview.with_blockers(
                            *target.reasons,
                            "task_checkpoint_unvalidated",
                        ),
                    )
                    for target in targets
                )
            blockers = list(pair.reasons)
            blockers.extend(reason for target in targets for reason in target.reasons)
            if not self.config.task_checkpoint_validated:
                blockers.append("task_checkpoint_unvalidated")
            active_view_reports: tuple[ActiveViewTargetReport, ...] = ()
            active_view_proposals: tuple[ObservationMoveProposal, ...] = ()
            active_view_observations: tuple[ActiveViewTargetObservation, ...] = ()
            if self.active_view is not None:
                try:
                    evaluate_batch = getattr(
                        self.active_view,
                        "evaluate_with_proposals",
                        None,
                    )
                    if callable(evaluate_batch):
                        batch = evaluate_batch(
                            detections=detections,
                            targets=targets,
                            rgb_stamp=pair.rgb.stamp,
                            robot_pose=robot_pose,
                            calibration=calibration,
                            arm_stationary=arm_stationary,
                            current_joints_deg=current_joints_deg,
                            refinement_evidence_ids=refinement_evidence_ids,
                            now_ns=now_ns,
                            fusion_context=result.fusion_context,
                            d435_verifications=d435_verifications,
                        )
                        if not isinstance(batch, ActiveViewEvaluationBatch):
                            raise ModelContractError(
                                "active-view adapter returned an invalid batch"
                            )
                        candidate_reports = batch.reports
                        active_view_proposals = batch.proposals
                        active_view_observations = batch.observations
                    else:
                        candidate_reports = tuple(
                            self.active_view.evaluate(
                                detections=detections,
                                targets=targets,
                                rgb_stamp=pair.rgb.stamp,
                                robot_pose=robot_pose,
                                calibration=calibration,
                                arm_stationary=arm_stationary,
                                refinement_evidence_ids=refinement_evidence_ids,
                                now_ns=now_ns,
                            )
                        )
                    if any(
                        not isinstance(report, ActiveViewTargetReport)
                        for report in candidate_reports
                    ):
                        raise ModelContractError("active-view adapter returned an invalid report")
                    active_view_reports = candidate_reports[:256]
                except Exception as active_view_error:
                    if isinstance(active_view_error, (KeyboardInterrupt, SystemExit)):
                        raise
                    detection_id = detections[0].detection_id if detections else 0
                    identity_id = targets[0].identity_id if targets else None
                    active_view_reports = (
                        ActiveViewTargetReport(
                            detection_id=detection_id,
                            identity_id=identity_id,
                            kind="none",
                            target_pose_id=None,
                            expires_ns=None,
                            coarse_center_xy_m=None,
                            valid_depth_points=0,
                            central_fraction=None,
                            depth_acceptable=None,
                            reasons=("active_view_adapter_unavailable",),
                            active_view_execution_enabled=False,
                        ),
                    )
                    active_view_proposals = ()
                    active_view_observations = ()
                    blockers.append("active_view_adapter_unavailable")
            return self._finish(
                pair=pair,
                started_ns=started_ns,
                targets=targets,
                annotations=annotations,
                model_ready=True,
                blockers=tuple(dict.fromkeys(blockers)),
                active_view_reports=active_view_reports,
                active_view_proposals=active_view_proposals,
                active_view_observations=active_view_observations,
            )
        except Exception as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            message = str(error).strip() or type(error).__name__
            return self._finish(
                pair=pair,
                started_ns=started_ns,
                targets=(),
                annotations=annotations,
                model_ready=False,
                blockers=("model_unavailable",),
                model_error=message[:512],
            )


def render_overlay(image_rgb: Any, result: OnlinePerceptionResult) -> np.ndarray:
    source = validated_rgb_image(image_rgb)
    if not isinstance(result, OnlinePerceptionResult):
        raise ModelContractError("overlay requires an OnlinePerceptionResult")
    visuals = build_target_visuals(
        result.annotations,
        result.targets,
        grasp_points_px={
            target.detection_id: target.grasp_preview.candidate.grasp_lumos_px
            for target in result.targets
            if target.grasp_preview is not None
            and target.grasp_preview.candidate is not None
        },
        grasp_execution_enabled=result.robot_execution_enabled,
    )
    return render_target_visuals(source, visuals, model_ready=result.model_ready)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IdentityReplayFormatError(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise IdentityReplayFormatError(f"{name} must be a non-empty string")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise IdentityReplayFormatError(f"{name} must be a positive integer")
    return value


def _local_file(config_path: Path, value: Any, name: str) -> Path:
    raw = _string(value, name)
    if "://" in raw:
        raise IdentityReplayFormatError(f"{name} must be a local file")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise IdentityReplayFormatError(f"{name} does not exist: {candidate}")
    return candidate


def load_online_vision_config(path: Path | str) -> OnlineVisionConfig:
    source = Path(path).resolve()
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise IdentityReplayFormatError(f"cannot read REMIND-3D config: {error}") from error
    raw = _mapping(raw, "REMIND-3D config")
    if raw.get("schema_version") != 1:
        raise IdentityReplayFormatError("REMIND-3D config schema_version must be 1")
    models = _mapping(raw.get("models"), "models")
    roles = _mapping(raw.get("roles"), "roles")
    online = _mapping(raw.get("online"), "online")
    timing = _mapping(raw.get("timing"), "timing")
    identity = _mapping(raw.get("identity"), "identity")
    instance_pose = _mapping(raw.get("instance_pose"), "instance_pose")
    limits = _mapping(raw.get("limits"), "limits")
    safety = _mapping(raw.get("safety"), "safety")
    if safety.get("robot_execution_enabled") is not False:
        raise IdentityReplayFormatError("robot_execution_enabled must remain false")
    if online.get("enabled") is not True:
        raise IdentityReplayFormatError("online.enabled must be true")
    if online.get("scheduling") != "latest_only":
        raise IdentityReplayFormatError("online scheduling must be latest_only")
    if models.get("label_set") != "coco":
        raise IdentityReplayFormatError("online fallback detector label_set must be coco")
    detector_device = _string(online.get("detector_device"), "detector_device")
    descriptor_device = _string(online.get("descriptor_device"), "descriptor_device")
    if not re.fullmatch(r"cuda:\d+", detector_device) or not re.fullmatch(
        r"cuda:\d+", descriptor_device
    ):
        raise IdentityReplayFormatError("online model devices must be explicit CUDA devices")
    task_validated = online.get("task_checkpoint_validated")
    if not isinstance(task_validated, bool):
        raise IdentityReplayFormatError("task_checkpoint_validated must be a boolean")
    accepted_task_labels: tuple[str, ...] = ()
    try:
        role_map = CameraRoleMap(
            canonical_rgb_source=_string(
                roles.get("canonical_rgb_source"), "canonical_rgb_source"
            ),
            metric_depth_source=_string(
                roles.get("metric_depth_source"), "metric_depth_source"
            ),
            debug_rgb_source=roles.get("debug_rgb_source"),
            fusion_mode=_string(roles.get("fusion_mode"), "fusion_mode"),
        )
        identity_config = PersistentIdentityConfig(**identity)
        perception_config = DualCameraConfig(
            max_frame_skew_ns=_positive_int(
                timing.get("max_frame_skew_ns"), "max_frame_skew_ns"
            ),
            max_frame_age_ns=_positive_int(
                timing.get("max_frame_age_ns"), "max_frame_age_ns"
            ),
            max_robot_pose_skew_ns=_positive_int(
                timing.get("max_robot_pose_skew_ns"), "max_robot_pose_skew_ns"
            ),
            min_depth_m=float(online.get("min_depth_m")),
            max_depth_m=float(online.get("max_depth_m")),
            pose=InstancePoseConfig(**instance_pose),
            roles=role_map,
        )
        detector_config_path = _local_file(
            source, models.get("detector_config"), "detector_config"
        )
        detector_checkpoint_path = _local_file(
            source, models.get("detector_checkpoint"), "detector_checkpoint"
        )
        descriptor_model_id = _string(
            models.get("primary_descriptor_id"), "primary_descriptor_id"
        )
        if task_validated:
            raw_labels = online.get("task_labels")
            if (
                not isinstance(raw_labels, list)
                or not raw_labels
                or any(not isinstance(label, str) or not label for label in raw_labels)
                or len(set(raw_labels)) != len(raw_labels)
            ):
                raise IdentityReplayFormatError(
                    "validated task checkpoint requires unique task_labels"
                )
            evidence_path = _local_file(
                source,
                online.get("task_checkpoint_evidence"),
                "task_checkpoint_evidence",
            )
            try:
                accepted_task_labels = validate_task_checkpoint(
                    evidence_path,
                    detector_config_path=detector_config_path,
                    detector_checkpoint_path=detector_checkpoint_path,
                    descriptor_model_id=descriptor_model_id,
                    requested_labels=tuple(raw_labels),
                )
            except ModelAcceptanceError as error:
                raise IdentityReplayFormatError(
                    f"invalid task checkpoint evidence: {error}"
                ) from error
        config = OnlineVisionConfig(
            roles=role_map,
            detector_backend=_string(models.get("detector_backend"), "detector_backend"),
            detector_config_path=detector_config_path,
            detector_checkpoint_path=detector_checkpoint_path,
            detector_labels=COCO_INSTANCE_LABELS,
            descriptor_model_id=descriptor_model_id,
            detector_device=detector_device,
            descriptor_device=descriptor_device,
            detector_min_score=float(models.get("detector_min_score")),
            dino_max_long_side=_positive_int(
                models.get("dino_max_long_side"), "dino_max_long_side"
            ),
            min_patch_coverage=float(models.get("min_patch_coverage")),
            task_checkpoint_validated=task_validated,
            accepted_task_labels=accepted_task_labels,
            latest_only=True,
            max_pending_frames=_positive_int(
                online.get("max_pending_frames"), "max_pending_frames"
            ),
            max_targets_per_frame=_positive_int(
                online.get("max_targets_per_frame"), "max_targets_per_frame"
            ),
            latency_p95_limit_ms=float(limits.get("latency_p95_limit_ms")),
            gpu_memory_limit_gib=float(limits.get("gpu_memory_limit_gib")),
            robot_execution_enabled=False,
            identity_config=identity_config,
            perception_config=perception_config,
        )
    except IdentityReplayFormatError:
        raise
    except (InvalidDataError, ModelContractError, TypeError, ValueError) as error:
        raise IdentityReplayFormatError(f"invalid online vision config: {error}") from error
    return config
