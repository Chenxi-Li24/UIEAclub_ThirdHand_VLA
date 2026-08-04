"""Strict, deterministic offline replay metrics for recorded vision artifacts."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


class ReplayFormatError(ValueError):
    """Raised when a replay manifest or referenced artifact is invalid."""


@dataclass(frozen=True)
class ReplayMetrics:
    frame_count: int
    registration_coverage: float
    valid_target_cloud_frames: int
    id_switches: int
    track_continuity: float
    latency_p50_ms: float
    latency_p95_ms: float
    dry_run_approval_count: int
    dry_run_rejection_count: int
    dry_run_approval_rate: float
    rejection_reasons: dict[str, int]
    calibration_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_count": self.frame_count,
            "registration_coverage": self.registration_coverage,
            "valid_target_cloud_frames": self.valid_target_cloud_frames,
            "id_switches": self.id_switches,
            "track_continuity": self.track_continuity,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "dry_run_approval_count": self.dry_run_approval_count,
            "dry_run_rejection_count": self.dry_run_rejection_count,
            "dry_run_approval_rate": self.dry_run_approval_rate,
            "rejection_reasons": dict(sorted(self.rejection_reasons.items())),
            "calibration_ids": list(self.calibration_ids),
        }


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ReplayFormatError(f"{name} must be an object")
    return value


def _relative_artifact(manifest_path: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ReplayFormatError("depth_npz must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReplayFormatError("depth_npz must be a safe relative path")
    root = manifest_path.parent.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ReplayFormatError("depth_npz must remain relative to the manifest") from error
    if not resolved.is_file():
        raise ReplayFormatError(f"depth_npz does not exist: {relative}")
    return resolved


def _nonnegative_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ReplayFormatError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ReplayFormatError(f"{name} must be numeric") from error
    if not np.isfinite(number) or number < 0.0:
        raise ReplayFormatError(f"{name} must be finite and non-negative")
    return number


def run_replay(manifest_path: Path | str) -> ReplayMetrics:
    path = Path(manifest_path).resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayFormatError(f"cannot read replay manifest: {error}") from error
    manifest = _mapping(manifest, "manifest")
    if manifest.get("schema_version") != 1:
        raise ReplayFormatError("unsupported schema_version; expected 1")
    calibration_id = manifest.get("calibration_id")
    if not isinstance(calibration_id, str) or not calibration_id.startswith("sha256:"):
        raise ReplayFormatError("manifest calibration_id must start with sha256:")
    minimum_cloud_points = manifest.get("min_target_cloud_points")
    if not isinstance(minimum_cloud_points, int) or minimum_cloud_points < 1:
        raise ReplayFormatError("min_target_cloud_points must be a positive integer")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ReplayFormatError("frames must be a non-empty array")
    depth_path = _relative_artifact(path, manifest.get("depth_npz"))

    frame_ids: set[int] = set()
    previous_timestamp = -1
    calibration_ids: set[str] = set()
    valid_depth_count = 0
    total_depth_count = 0
    valid_target_cloud_frames = 0
    previous_track_ids: dict[str, int] = {}
    association_transitions = 0
    id_switches = 0
    latencies = []
    approval_count = 0
    rejection_reasons: Counter[str] = Counter()

    try:
        depth_archive = np.load(depth_path, allow_pickle=False)
    except (OSError, ValueError) as error:
        raise ReplayFormatError(f"cannot load depth_npz: {error}") from error
    try:
        for index, raw_frame in enumerate(frames):
            frame = _mapping(raw_frame, f"frames[{index}]")
            frame_id = frame.get("frame_id")
            timestamp = frame.get("monotonic_ns")
            if not isinstance(frame_id, int) or frame_id < 0 or frame_id in frame_ids:
                raise ReplayFormatError("frame_id values must be unique non-negative integers")
            if not isinstance(timestamp, int) or timestamp <= previous_timestamp:
                raise ReplayFormatError("frame timestamps must be strictly increasing")
            frame_ids.add(frame_id)
            previous_timestamp = timestamp

            frame_calibration = frame.get("calibration_id")
            if frame_calibration != calibration_id:
                raise ReplayFormatError("frame calibration does not match manifest calibration")
            calibration_ids.add(frame_calibration)

            depth_key = frame.get("depth_key")
            if not isinstance(depth_key, str) or depth_key not in depth_archive.files:
                raise ReplayFormatError(f"missing depth array for frames[{index}]")
            depth = np.asarray(depth_archive[depth_key], dtype=float)
            if depth.ndim != 2 or depth.size == 0:
                raise ReplayFormatError("each depth array must be a non-empty 2D image")
            valid_depth_count += int((np.isfinite(depth) & (depth > 0.0)).sum())
            total_depth_count += int(depth.size)

            cloud_points = frame.get("target_cloud_points")
            if not isinstance(cloud_points, int) or cloud_points < 0:
                raise ReplayFormatError("target_cloud_points must be a non-negative integer")
            if cloud_points >= minimum_cloud_points:
                valid_target_cloud_frames += 1

            object_tracks = _mapping(frame.get("object_tracks"), "object_tracks")
            for object_key in sorted(object_tracks):
                track_id = object_tracks[object_key]
                if not isinstance(object_key, str) or not object_key:
                    raise ReplayFormatError("object track keys must be non-empty strings")
                if not isinstance(track_id, int) or track_id < 1:
                    raise ReplayFormatError("track IDs must be positive integers")
                if object_key in previous_track_ids:
                    association_transitions += 1
                    if previous_track_ids[object_key] != track_id:
                        id_switches += 1
                previous_track_ids[object_key] = track_id

            latencies.append(_nonnegative_number(frame.get("latency_ms"), "latency_ms"))
            dry_run = _mapping(frame.get("dry_run"), "dry_run")
            approved = dry_run.get("approved")
            reasons = dry_run.get("reasons")
            if not isinstance(approved, bool) or not isinstance(reasons, list):
                raise ReplayFormatError("dry_run requires boolean approved and array reasons")
            if not all(isinstance(reason, str) and reason for reason in reasons):
                raise ReplayFormatError("dry_run reasons must be non-empty strings")
            if approved and reasons:
                raise ReplayFormatError("approved dry_run cannot contain rejection reasons")
            if not approved and not reasons:
                raise ReplayFormatError("rejected dry_run must contain rejection reasons")
            if approved:
                approval_count += 1
            else:
                rejection_reasons.update(reasons)
    finally:
        depth_archive.close()

    latency_p50, latency_p95 = np.percentile(np.asarray(latencies), [50, 95])
    rejection_count = len(frames) - approval_count
    continuity = (
        1.0
        if association_transitions == 0
        else (association_transitions - id_switches) / association_transitions
    )
    return ReplayMetrics(
        frame_count=len(frames),
        registration_coverage=valid_depth_count / total_depth_count,
        valid_target_cloud_frames=valid_target_cloud_frames,
        id_switches=id_switches,
        track_continuity=continuity,
        latency_p50_ms=float(latency_p50),
        latency_p95_ms=float(latency_p95),
        dry_run_approval_count=approval_count,
        dry_run_rejection_count=rejection_count,
        dry_run_approval_rate=approval_count / len(frames),
        rejection_reasons=dict(rejection_reasons),
        calibration_ids=tuple(sorted(calibration_ids)),
    )


def write_metrics_atomic(path: Path | str, metrics: ReplayMetrics) -> None:
    destination = Path(path)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    payload = json.dumps(metrics.to_dict(), indent=2, sort_keys=True) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(destination)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    write_metrics_atomic(arguments.output, run_replay(arguments.manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
