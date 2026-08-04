"""Deterministic, execution-free replay for persistent instance identity."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import yaml

from vision.identity import (
    IdentityObservation,
    PersistentIdentityConfig,
    PersistentIdentityMemory,
)
from vision.types import FrameStamp, InvalidDataError, PoseEstimate


class IdentityReplayFormatError(ValueError):
    """Raised when identity replay input is unsafe or malformed."""


@dataclass(frozen=True)
class ReplayIdentityAssignment:
    observation_id: int
    object_key: str
    identity_id: Optional[int]
    status: str
    cost: Optional[float]
    reason: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost": self.cost,
            "identity_id": self.identity_id,
            "object_key": self.object_key,
            "observation_id": self.observation_id,
            "reason": self.reason,
            "status": self.status,
        }


@dataclass(frozen=True)
class ReplayIdentityFrame:
    frame_id: int
    monotonic_ns: int
    assignments: tuple[ReplayIdentityAssignment, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignments": [item.to_dict() for item in self.assignments],
            "frame_id": self.frame_id,
            "monotonic_ns": self.monotonic_ns,
        }


@dataclass(frozen=True)
class IdentityReplayMetrics:
    frame_count: int
    observation_count: int
    assigned_count: int
    new_identity_count: int
    ambiguous_count: int
    forced_ambiguous_assignments: int
    known_identity_transitions: int
    id_switches: int

    def to_dict(self) -> dict[str, int]:
        return {
            "ambiguous_count": self.ambiguous_count,
            "assigned_count": self.assigned_count,
            "forced_ambiguous_assignments": self.forced_ambiguous_assignments,
            "frame_count": self.frame_count,
            "id_switches": self.id_switches,
            "known_identity_transitions": self.known_identity_transitions,
            "new_identity_count": self.new_identity_count,
            "observation_count": self.observation_count,
        }


@dataclass(frozen=True)
class IdentityReplayReport:
    schema_version: int
    calibration_id: str
    frames: tuple[ReplayIdentityFrame, ...]
    metrics: IdentityReplayMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibration_id": self.calibration_id,
            "frames": [frame.to_dict() for frame in self.frames],
            "metrics": self.metrics.to_dict(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class Remind3DDeploymentConfig:
    canonical_image: str
    detector_backend: str
    primary_descriptor: str
    fallback_descriptor: str
    dino_max_long_side: int
    gpu_memory_limit_gib: float
    latency_p95_limit_ms: float
    robot_execution_enabled: bool


FORBIDDEN_EXECUTION_FIELDS = {"command", "execute", "gripper", "move", "trajectory"}


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise IdentityReplayFormatError(f"{name} must be an object")
    return value


def _reject_execution_fields(value: Any, location: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_EXECUTION_FIELDS:
                raise IdentityReplayFormatError(
                    f"forbidden execution field {key!r} at {location}"
                )
            _reject_execution_fields(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_execution_fields(item, f"{location}[{index}]")


def _relative_artifact(manifest_path: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise IdentityReplayFormatError("descriptor_npz must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise IdentityReplayFormatError("descriptor_npz must be a safe relative path")
    root = manifest_path.parent.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise IdentityReplayFormatError(
            "descriptor_npz must remain relative to the manifest"
        ) from error
    if not resolved.is_file():
        raise IdentityReplayFormatError(f"descriptor artifact does not exist: {relative}")
    return resolved


def _finite_probability(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise IdentityReplayFormatError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise IdentityReplayFormatError(f"{name} must be numeric") from error
    if not np.isfinite(number) or not 0.0 <= number <= 1.0:
        raise IdentityReplayFormatError(f"{name} must be within [0, 1]")
    return number


def _pose_from_json(
    raw: Mapping[str, Any],
    frame_id: int,
    monotonic_ns: int,
    calibration_id: str,
) -> Optional[PoseEstimate]:
    xyz = raw.get("pose_xyz_m")
    variance = raw.get("pose_variance_m2")
    if xyz is None and variance is None:
        return None
    if xyz is None or variance is None:
        raise IdentityReplayFormatError("pose_xyz_m and pose_variance_m2 must both be set")
    try:
        xyz_array = np.asarray(xyz, dtype=float)
        variance_value = float(variance)
    except (TypeError, ValueError) as error:
        raise IdentityReplayFormatError("pose fields must be numeric") from error
    if xyz_array.shape != (3,) or not np.isfinite(xyz_array).all():
        raise IdentityReplayFormatError("pose_xyz_m must be a finite three-vector")
    if not np.isfinite(variance_value) or variance_value < 0.0:
        raise IdentityReplayFormatError("pose_variance_m2 must be finite and non-negative")
    return PoseEstimate(
        xyz_m=xyz_array,
        covariance_m2=np.eye(3) * variance_value,
        frame="robot_base",
        stamp=FrameStamp("lumos+d435", frame_id, monotonic_ns),
        calibration_id=calibration_id,
    )


def _identity_config(value: Any) -> PersistentIdentityConfig:
    raw = _mapping(value, "identity_config")
    try:
        return PersistentIdentityConfig(**raw)
    except (TypeError, InvalidDataError) as error:
        raise IdentityReplayFormatError(f"invalid identity_config: {error}") from error


def run_identity_replay(manifest_path: Path | str) -> IdentityReplayReport:
    path = Path(manifest_path).resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IdentityReplayFormatError(f"cannot read identity replay manifest: {error}") from error
    manifest = _mapping(manifest, "manifest")
    _reject_execution_fields(manifest)
    if manifest.get("schema_version") != 1:
        raise IdentityReplayFormatError("unsupported schema_version; expected 1")
    calibration_id = manifest.get("calibration_id")
    if not isinstance(calibration_id, str) or not calibration_id.startswith("sha256:"):
        raise IdentityReplayFormatError("calibration_id must start with sha256:")
    config = _identity_config(manifest.get("identity_config"))
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise IdentityReplayFormatError("frames must be a non-empty array")
    descriptor_path = _relative_artifact(path, manifest.get("descriptor_npz"))

    try:
        archive = np.load(descriptor_path, allow_pickle=False)
    except (OSError, ValueError) as error:
        raise IdentityReplayFormatError(f"cannot load descriptor artifact: {error}") from error

    engine = PersistentIdentityMemory(config)
    frame_reports = []
    seen_frame_ids: set[int] = set()
    previous_timestamp = -1
    previous_object_identities: dict[str, int] = {}
    observation_count = 0
    assigned_count = 0
    new_identity_count = 0
    ambiguous_count = 0
    forced_ambiguous_assignments = 0
    known_identity_transitions = 0
    id_switches = 0
    try:
        for frame_index, frame_value in enumerate(frames):
            frame = _mapping(frame_value, f"frames[{frame_index}]")
            frame_id = frame.get("frame_id")
            monotonic_ns = frame.get("monotonic_ns")
            if not isinstance(frame_id, int) or frame_id < 0 or frame_id in seen_frame_ids:
                raise IdentityReplayFormatError(
                    "frame_id values must be unique non-negative integers"
                )
            if not isinstance(monotonic_ns, int) or monotonic_ns <= previous_timestamp:
                raise IdentityReplayFormatError("frame timestamps must be strictly increasing")
            seen_frame_ids.add(frame_id)
            previous_timestamp = monotonic_ns
            observation_values = frame.get("observations")
            if not isinstance(observation_values, list):
                raise IdentityReplayFormatError("observations must be an array")

            observations = []
            object_keys: dict[int, str] = {}
            for observation_index, observation_value in enumerate(observation_values):
                raw = _mapping(
                    observation_value,
                    f"frames[{frame_index}].observations[{observation_index}]",
                )
                observation_id = raw.get("observation_id")
                object_key = raw.get("object_key")
                label = raw.get("label")
                descriptor_key = raw.get("descriptor_key")
                if not isinstance(observation_id, int) or observation_id < 0:
                    raise IdentityReplayFormatError("observation_id must be a non-negative integer")
                if not isinstance(object_key, str) or not object_key:
                    raise IdentityReplayFormatError("object_key must be a non-empty string")
                if not isinstance(label, str) or not label:
                    raise IdentityReplayFormatError("label must be a non-empty string")
                if not isinstance(descriptor_key, str) or descriptor_key not in archive.files:
                    raise IdentityReplayFormatError(
                        f"descriptor key is missing from artifact: {descriptor_key!r}"
                    )
                descriptor = np.asarray(archive[descriptor_key], dtype=float)
                appearance_stamp = FrameStamp("lumos", frame_id, monotonic_ns)
                try:
                    item = IdentityObservation(
                        observation_id=observation_id,
                        label=label,
                        confidence=_finite_probability(raw.get("confidence"), "confidence"),
                        visibility=_finite_probability(raw.get("visibility"), "visibility"),
                        descriptor=descriptor,
                        stamp=appearance_stamp,
                        pose=_pose_from_json(raw, frame_id, monotonic_ns, calibration_id),
                    )
                except InvalidDataError as error:
                    raise IdentityReplayFormatError(
                        f"invalid identity observation: {error}"
                    ) from error
                observations.append(item)
                object_keys[observation_id] = object_key

            try:
                update = engine.update(observations, monotonic_ns)
            except InvalidDataError as error:
                raise IdentityReplayFormatError(
                    f"identity replay update failed: {error}"
                ) from error
            assignments = []
            for item in update.assignments:
                object_key = object_keys[item.observation_id]
                status = item.status.value
                observation_count += 1
                if item.identity_id is not None:
                    assigned_count += 1
                if item.reason == "new_identity":
                    new_identity_count += 1
                if status == "ambiguous":
                    ambiguous_count += 1
                    if item.identity_id is not None:
                        forced_ambiguous_assignments += 1
                if item.identity_id is not None:
                    previous_identity = previous_object_identities.get(object_key)
                    if previous_identity is not None:
                        known_identity_transitions += 1
                        if previous_identity != item.identity_id:
                            id_switches += 1
                    previous_object_identities[object_key] = item.identity_id
                assignments.append(
                    ReplayIdentityAssignment(
                        observation_id=item.observation_id,
                        object_key=object_key,
                        identity_id=item.identity_id,
                        status=status,
                        cost=item.cost,
                        reason=item.reason,
                    )
                )
            frame_reports.append(
                ReplayIdentityFrame(
                    frame_id=frame_id,
                    monotonic_ns=monotonic_ns,
                    assignments=tuple(assignments),
                )
            )
    finally:
        archive.close()

    metrics = IdentityReplayMetrics(
        frame_count=len(frame_reports),
        observation_count=observation_count,
        assigned_count=assigned_count,
        new_identity_count=new_identity_count,
        ambiguous_count=ambiguous_count,
        forced_ambiguous_assignments=forced_ambiguous_assignments,
        known_identity_transitions=known_identity_transitions,
        id_switches=id_switches,
    )
    return IdentityReplayReport(
        schema_version=1,
        calibration_id=calibration_id,
        frames=tuple(frame_reports),
        metrics=metrics,
    )


def write_report_atomic(path: Path | str, report: IdentityReplayReport) -> None:
    destination = Path(path)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(destination)


def load_remind3d_config(path: Path | str) -> Remind3DDeploymentConfig:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise IdentityReplayFormatError(f"cannot read REMIND-3D config: {error}") from error
    raw = _mapping(raw, "REMIND-3D config")
    if raw.get("schema_version") != 1:
        raise IdentityReplayFormatError("REMIND-3D config schema_version must be 1")
    models = _mapping(raw.get("models"), "models")
    limits = _mapping(raw.get("limits"), "limits")
    safety = _mapping(raw.get("safety"), "safety")
    execution_enabled = safety.get("robot_execution_enabled")
    if execution_enabled is not False:
        raise IdentityReplayFormatError("robot_execution_enabled must remain false")
    try:
        result = Remind3DDeploymentConfig(
            canonical_image=str(raw["canonical_image"]),
            detector_backend=str(models["detector_backend"]),
            primary_descriptor=str(models["primary_descriptor"]),
            fallback_descriptor=str(models["fallback_descriptor"]),
            dino_max_long_side=int(models["dino_max_long_side"]),
            gpu_memory_limit_gib=float(limits["gpu_memory_limit_gib"]),
            latency_p95_limit_ms=float(limits["latency_p95_limit_ms"]),
            robot_execution_enabled=False,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise IdentityReplayFormatError(f"REMIND-3D config is incomplete: {error}") from error
    if not result.canonical_image or not result.detector_backend:
        raise IdentityReplayFormatError("REMIND-3D model identifiers cannot be empty")
    if result.dino_max_long_side < 1:
        raise IdentityReplayFormatError("dino_max_long_side must be positive")
    if (
        not np.isfinite([result.gpu_memory_limit_gib, result.latency_p95_limit_ms]).all()
        or result.gpu_memory_limit_gib <= 0.0
        or result.latency_p95_limit_ms <= 0.0
    ):
        raise IdentityReplayFormatError("REMIND-3D limits must be finite and positive")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    write_report_atomic(arguments.output, run_identity_replay(arguments.manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
