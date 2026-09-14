"""Frozen, non-executing previews shaped like the local Startouch bridge."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from ..runtime.models import SEMVER_PATTERN, FrozenModel

JointVector = tuple[float, float, float, float, float, float]
Vector3 = tuple[float, float, float]
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


def _finite_tuple(values: tuple[float, ...]) -> tuple[float, ...]:
    if not all(math.isfinite(value) for value in values):
        raise ValueError("preview values must be finite")
    return values


class JointWaypointPreview(FrozenModel):
    command_type: Literal["move_joint_path"]
    waypoints_rad: tuple[JointVector, ...] = Field(min_length=1)
    time_sec: float = Field(gt=0.0)
    speed_percent: float = Field(gt=0.0)
    angle_unit: Literal["rad"]

    @field_validator("waypoints_rad")
    @classmethod
    def finite_waypoints(
        cls, values: tuple[JointVector, ...]
    ) -> tuple[JointVector, ...]:
        for waypoint in values:
            _finite_tuple(waypoint)
        return values

    @field_validator("time_sec", "speed_percent")
    @classmethod
    def finite_scalars(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("preview values must be finite")
        return value


class LinearPosePreview(FrozenModel):
    command_type: Literal["move_l"]
    position_m: Vector3
    euler_rad: Vector3
    frame: str = Field(min_length=1)
    calibration_id: str = Field(min_length=1)
    time_sec: float = Field(gt=0.0)
    position_tolerance_m: float = Field(gt=0.0)
    orientation_tolerance_rad: float = Field(gt=0.0)
    position_unit: Literal["m"]
    orientation_unit: Literal["rad"]

    @field_validator("position_m", "euler_rad")
    @classmethod
    def finite_vectors(cls, values: Vector3) -> Vector3:
        _finite_tuple(values)
        return values

    @field_validator(
        "time_sec", "position_tolerance_m", "orientation_tolerance_rad"
    )
    @classmethod
    def finite_scalars(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("preview values must be finite")
        return value


class GripperPreview(FrozenModel):
    command_type: Literal["gripper"]
    position_normalized: float | None = Field(default=None, ge=0.0, le=1.0)
    distance_m: float | None = Field(default=None, ge=0.0)
    position_unit: Literal["normalized", "m"]

    @model_validator(mode="after")
    def exactly_one_matching_unit(self) -> GripperPreview:
        if (self.position_normalized is None) == (self.distance_m is None):
            raise ValueError("exactly one gripper target must be specified")
        if self.position_normalized is not None and self.position_unit != "normalized":
            raise ValueError("normalized target requires normalized unit")
        if self.distance_m is not None and self.position_unit != "m":
            raise ValueError("distance target requires metre unit")
        value = (
            self.position_normalized
            if self.position_normalized is not None
            else self.distance_m
        )
        if value is None or not math.isfinite(value):
            raise ValueError("preview values must be finite")
        return self


CommandPreview = Annotated[
    JointWaypointPreview | LinearPosePreview | GripperPreview,
    Field(discriminator="command_type"),
]


class StartouchCommandPreview(FrozenModel):
    request_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    attempt: int = Field(ge=0)
    policy_id: str = Field(min_length=1)
    policy_version: str
    contract_version: str
    evidence_kind: Literal["shadow_command_preview"] = "shadow_command_preview"
    robot_execution_enabled: Literal[False] = False
    can_execute_world: Literal[False] = False
    command: CommandPreview

    @field_validator("policy_version", "contract_version")
    @classmethod
    def semantic_version(cls, value: str) -> str:
        if not SEMVER_PATTERN.fullmatch(value):
            raise ValueError("versions must be semantic x.y.z")
        return value


class ShadowLimits(FrozenModel):
    schema_version: str
    source_path: str = Field(min_length=1)
    source_commit: str
    robot_execution_enabled: Literal[False]
    allowed_frames: tuple[str, ...] = Field(min_length=1)
    allowed_calibration_ids: tuple[str, ...] = Field(min_length=1)
    joint_min_rad: JointVector
    joint_max_rad: JointVector
    duration_min_sec: float = Field(gt=0.0)
    duration_max_sec: float = Field(gt=0.0)
    speed_min_percent: float = Field(gt=0.0)
    speed_max_percent: float = Field(gt=0.0, le=100.0)
    position_tolerance_min_m: float = Field(gt=0.0)
    position_tolerance_max_m: float = Field(gt=0.0)
    orientation_tolerance_min_rad: float = Field(gt=0.0)
    orientation_tolerance_max_rad: float = Field(gt=0.0)
    gripper_max_distance_m: float = Field(gt=0.0)

    @field_validator("schema_version")
    @classmethod
    def semantic_version(cls, value: str) -> str:
        if not SEMVER_PATTERN.fullmatch(value):
            raise ValueError("schema version must be semantic x.y.z")
        return value

    @field_validator("source_commit")
    @classmethod
    def pinned_commit(cls, value: str) -> str:
        if not COMMIT_PATTERN.fullmatch(value):
            raise ValueError("source_commit must be a full lowercase git hash")
        return value

    @model_validator(mode="after")
    def ordered_limits(self) -> ShadowLimits:
        numeric = (
            self.joint_min_rad
            + self.joint_max_rad
            + (
                self.duration_min_sec,
                self.duration_max_sec,
                self.speed_min_percent,
                self.speed_max_percent,
                self.position_tolerance_min_m,
                self.position_tolerance_max_m,
                self.orientation_tolerance_min_rad,
                self.orientation_tolerance_max_rad,
                self.gripper_max_distance_m,
            )
        )
        _finite_tuple(numeric)
        if any(low >= high for low, high in zip(self.joint_min_rad, self.joint_max_rad)):
            raise ValueError("joint limits must be ordered")
        for low, high, name in (
            (self.duration_min_sec, self.duration_max_sec, "duration"),
            (self.speed_min_percent, self.speed_max_percent, "speed"),
            (
                self.position_tolerance_min_m,
                self.position_tolerance_max_m,
                "position tolerance",
            ),
            (
                self.orientation_tolerance_min_rad,
                self.orientation_tolerance_max_rad,
                "orientation tolerance",
            ),
        ):
            if low > high:
                raise ValueError(f"{name} limits must be ordered")
        return self

    def validate_preview(self, preview: StartouchCommandPreview) -> None:
        command = preview.command
        if isinstance(command, JointWaypointPreview):
            self._validate_duration(command.time_sec)
            if not self.speed_min_percent <= command.speed_percent <= self.speed_max_percent:
                raise ValueError("speed is outside shadow limits")
            for waypoint in command.waypoints_rad:
                for index, (value, low, high) in enumerate(
                    zip(waypoint, self.joint_min_rad, self.joint_max_rad, strict=True),
                    start=1,
                ):
                    if not low <= value <= high:
                        raise ValueError(f"joint {index} is outside shadow limits")
            return
        if isinstance(command, LinearPosePreview):
            self._validate_duration(command.time_sec)
            if command.frame not in self.allowed_frames:
                raise ValueError("frame is not allowed by shadow limits")
            if command.calibration_id not in self.allowed_calibration_ids:
                raise ValueError("calibration is not allowed by shadow limits")
            if not (
                self.position_tolerance_min_m
                <= command.position_tolerance_m
                <= self.position_tolerance_max_m
            ):
                raise ValueError("position tolerance is outside shadow limits")
            if not (
                self.orientation_tolerance_min_rad
                <= command.orientation_tolerance_rad
                <= self.orientation_tolerance_max_rad
            ):
                raise ValueError("orientation tolerance is outside shadow limits")
            return
        if command.distance_m is not None and command.distance_m > self.gripper_max_distance_m:
            raise ValueError("gripper distance is outside shadow limits")

    def _validate_duration(self, value: float) -> None:
        if not self.duration_min_sec <= value <= self.duration_max_sec:
            raise ValueError("duration is outside shadow limits")


def load_shadow_limits(path: Path) -> ShadowLimits:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read shadow limits {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("shadow limits must contain a mapping")
    try:
        return ShadowLimits.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"invalid shadow limits {path}: {exc}") from exc


__all__ = [
    "GripperPreview",
    "JointWaypointPreview",
    "LinearPosePreview",
    "ShadowLimits",
    "StartouchCommandPreview",
    "load_shadow_limits",
]
