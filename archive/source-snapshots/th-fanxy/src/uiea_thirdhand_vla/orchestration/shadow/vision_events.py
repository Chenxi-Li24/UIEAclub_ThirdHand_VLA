"""Strict adapter for the public ThirdHand detection-result event boundary."""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ..runtime.models import (
    EvidenceRef,
    Fact,
    ObjectState,
    Observation,
    RobotState,
)
from ..runtime.trace import content_id


class FrozenEventModel(BaseModel):
    """Immutable, finite JSON model used at the process boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class VisionIdentityStatus(str, Enum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    OCCLUDED = "occluded"
    INACTIVE = "inactive"
    AMBIGUOUS = "ambiguous"


class VisionIdentityMemory(FrozenEventModel):
    hits: int = Field(ge=0)
    work_prototype_count: int = Field(ge=0)
    stable_prototype_count: int = Field(ge=0)
    appearance_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    association_cost: float | None = Field(default=None, ge=0.0)
    association_reason: str | None = None


class VisionPose(FrozenEventModel):
    calibration_id: str = Field(min_length=1)
    covariance_m2: tuple[tuple[float, ...], ...]
    frame: str = Field(min_length=1)
    monotonic_ns: int = Field(ge=0)
    xyz_m: tuple[float, float, float]

    @model_validator(mode="after")
    def valid_covariance(self) -> VisionPose:
        if len(self.covariance_m2) != 3 or any(
            len(row) != 3 for row in self.covariance_m2
        ):
            raise ValueError("covariance_m2 must be a finite 3x3 matrix")
        diagonal = tuple(self.covariance_m2[index][index] for index in range(3))
        if any(value < 0.0 for value in diagonal):
            raise ValueError("covariance_m2 diagonal must be non-negative")
        return self

    @property
    def position_std_m(self) -> float:
        return math.sqrt(max(self.covariance_m2[index][index] for index in range(3)))


class VisionTarget(FrozenEventModel):
    actionable: bool
    detection_id: int = Field(ge=0)
    identity_id: int | None = Field(default=None, ge=0)
    identity_status: VisionIdentityStatus
    identity_memory: VisionIdentityMemory
    label: str = Field(min_length=1)
    grasp_preview: dict[str, JsonValue] | None = None
    pose: VisionPose | None = None
    reasons: tuple[str, ...] = ()
    registered_depth_points: int = Field(ge=0)
    score: float = Field(ge=0.0, le=1.0)


class VisionEvent(FrozenEventModel):
    type: Literal["detection_result"]
    blockers: tuple[str, ...]
    active_view_reports: tuple[dict[str, JsonValue], ...]
    canonical_rgb_source: str = Field(min_length=1)
    frame_id: int = Field(ge=0)
    gpu_memory_reserved_gib: float | None = Field(default=None, ge=0.0)
    latency_ms: float = Field(ge=0.0)
    latency_p95_ms: float = Field(ge=0.0)
    metric_depth_source: str = Field(min_length=1)
    model_error: str | None = None
    model_ready: bool
    monotonic_ns: int = Field(ge=0)
    robot_execution_enabled: Literal[False]
    source_sequence: int = Field(ge=0)
    targets: tuple[VisionTarget, ...]
    task_checkpoint_validated: bool
    ts: int = Field(ge=0)

    @model_validator(mode="after")
    def consistent_frame_identity(self) -> VisionEvent:
        if self.frame_id != self.source_sequence:
            raise ValueError("frame_id must equal source_sequence")
        detection_ids = tuple(target.detection_id for target in self.targets)
        if len(detection_ids) != len(set(detection_ids)):
            raise ValueError("target detection IDs must be unique")
        identity_ids = tuple(
            target.identity_id for target in self.targets if target.identity_id is not None
        )
        if len(identity_ids) != len(set(identity_ids)):
            raise ValueError("target identity IDs must be unique")
        return self


class VisionEventAdapter:
    """Bind public vision events to one explicit orchestration episode."""

    def __init__(self, episode_id: str) -> None:
        if not episode_id:
            raise ValueError("episode_id must be non-empty")
        self._episode_id = episode_id

    def to_observation(
        self,
        event: VisionEvent,
        robot: RobotState | None = None,
    ) -> Observation:
        event_evidence_id = content_id(event)
        evidence_ids = (event_evidence_id,)
        blocked = bool(event.blockers)
        objects: list[ObjectState] = []
        unbound = 0
        for target in event.targets:
            if target.identity_id is None:
                unbound += 1
                continue
            pose = target.pose
            depth_valid = bool(
                pose is not None
                and target.registered_depth_points > 0
                and pose.frame == "robot_base"
                and pose.monotonic_ns == event.monotonic_ns
            )
            confirmed = target.identity_status is VisionIdentityStatus.CONFIRMED
            ambiguous = not confirmed or any(
                "ambigu" in reason.lower() for reason in target.reasons
            )
            actionable = bool(
                target.actionable
                and confirmed
                and not ambiguous
                and depth_valid
                and event.model_ready
                and event.task_checkpoint_validated
                and not blocked
            )
            visible = target.identity_status not in {
                VisionIdentityStatus.INACTIVE,
                VisionIdentityStatus.OCCLUDED,
            }
            objects.append(
                ObjectState(
                    identity_id=target.identity_id,
                    label=target.label,
                    visible=visible,
                    ambiguous=ambiguous,
                    actionable=actionable,
                    depth_valid=depth_valid,
                    position_std_m=None if pose is None else pose.position_std_m,
                    evidence_ids=evidence_ids,
                )
            )
        facts = (
            Fact(
                name="vision_model_ready",
                value=event.model_ready,
                evidence_ids=evidence_ids,
            ),
            Fact(
                name="task_checkpoint_validated",
                value=event.task_checkpoint_validated,
                evidence_ids=evidence_ids,
            ),
            Fact(name="vision_blocked", value=blocked, evidence_ids=evidence_ids),
            Fact(name="unbound_target_count", value=unbound, evidence_ids=evidence_ids),
            Fact(name="robot_execution_enabled", value=False, evidence_ids=evidence_ids),
        )
        evidence = EvidenceRef(
            evidence_id=event_evidence_id,
            kind="thirdhand_vision_event",
            source=event.canonical_rgb_source,
            observed_monotonic_ns=event.monotonic_ns,
        )
        return Observation(
            episode_id=self._episode_id,
            snapshot_id=f"vision:{event.source_sequence}:{event_evidence_id[7:19]}",
            sequence=event.source_sequence,
            monotonic_ns=event.monotonic_ns,
            source="thirdhand.vision.detection_result",
            source_version="1",
            objects=tuple(objects),
            robot=robot,
            facts=facts,
            evidence=(evidence,),
        )


__all__ = [
    "VisionEvent",
    "VisionEventAdapter",
    "VisionIdentityMemory",
    "VisionIdentityStatus",
    "VisionPose",
    "VisionTarget",
]
