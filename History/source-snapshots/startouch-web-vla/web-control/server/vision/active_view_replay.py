"""Bounded deterministic replay for active-view Dry Run decisions."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from vision_models.active_view_online import load_active_view_config_dict

from .active_view_planner import propose_refinement, select_observation_pose
from .active_view_types import CoarseTargetEstimate, DepthQuality
from .types import FrameStamp, InvalidDataError


MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_FRAMES = 10_000
MAX_TARGETS_PER_FRAME = 256
MAX_OBSERVATION_POSES = 64
FORBIDDEN_COMMAND_FIELDS = {
    "can",
    "cmd",
    "command",
    "gripper",
    "move",
    "move_joint",
    "move_l",
    "robot_command",
    "trajectory",
}


class ActiveViewReplayError(ValueError):
    """Raised when active-view replay evidence is unsafe or malformed."""


@dataclass(frozen=True)
class ActiveViewReplayMetrics:
    frame_count: int
    proposal_count: int
    pose_selection_accuracy: float
    depth_quality_acceptance_rate: float
    identity_switches: int
    rejection_reasons: dict[str, int]
    execution_proposals: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "depth_quality_acceptance_rate": self.depth_quality_acceptance_rate,
            "execution_proposals": self.execution_proposals,
            "frame_count": self.frame_count,
            "identity_switches": self.identity_switches,
            "pose_selection_accuracy": self.pose_selection_accuracy,
            "proposal_count": self.proposal_count,
            "rejection_reasons": dict(sorted(self.rejection_reasons.items())),
        }


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ActiveViewReplayError(f"{name} must be an object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    required: set[str],
    optional: set[str],
    name: str,
) -> None:
    keys = set(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise ActiveViewReplayError(f"{name} is missing keys: {sorted(missing)}")
    if unknown:
        raise ActiveViewReplayError(f"{name} has unknown keys: {sorted(unknown)}")


def _reject_unsafe_fields(value: Any, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_COMMAND_FIELDS:
                raise ActiveViewReplayError(f"robot command field is forbidden: {path}.{key}")
            if "execution_enabled" in normalized and child is not False:
                raise ActiveViewReplayError("active-view replay execution must remain disabled")
            _reject_unsafe_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_unsafe_fields(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if ".." in Path(value).parts:
            raise ActiveViewReplayError(f"path traversal is forbidden at {path}")


def _json_constant(value: str) -> None:
    raise ActiveViewReplayError(f"non-finite JSON number is forbidden: {value}")


def _read_manifest(path: Path) -> Mapping[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ActiveViewReplayError(f"cannot stat replay manifest: {exc}") from exc
    if size > MAX_MANIFEST_BYTES:
        raise ActiveViewReplayError("active-view replay manifest exceeds 8 MiB")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), parse_constant=_json_constant)
    except ActiveViewReplayError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActiveViewReplayError(f"cannot read active-view replay manifest: {exc}") from exc
    manifest = _mapping(raw, "manifest")
    _reject_unsafe_fields(manifest)
    _exact_keys(manifest, {"schema_version", "config", "frames"}, set(), "manifest")
    if isinstance(manifest["schema_version"], bool) or manifest["schema_version"] != 1:
        raise ActiveViewReplayError("unsupported active-view replay schema version")
    return manifest


def _target_common(target: Mapping[str, Any], name: str, calibration_id: str) -> None:
    identity_id = target.get("identity_id")
    if isinstance(identity_id, bool) or not isinstance(identity_id, int) or identity_id < 0:
        raise ActiveViewReplayError(f"{name}.identity_id must be non-negative")
    if not isinstance(target.get("track_key"), str) or not target["track_key"]:
        raise ActiveViewReplayError(f"{name}.track_key must be a non-empty string")
    if not isinstance(target.get("label"), str) or not target["label"]:
        raise ActiveViewReplayError(f"{name}.label must be a non-empty string")
    if target.get("calibration_id") != calibration_id:
        raise ActiveViewReplayError(f"{name} calibration does not match replay config")


def _coarse_proposal(target: Mapping[str, Any], stamp: FrameStamp, config):
    estimate = CoarseTargetEstimate(
        identity_id=target["identity_id"],
        center_xy_m=target["center_xy_m"],
        covariance_xy_m2=target["covariance_xy_m2"],
        samples_xy_m=target["samples_xy_m"],
        source_stamp=stamp,
        calibration_id=target["calibration_id"],
    )
    return select_observation_pose(
        estimate=estimate,
        poses=config.observation_poses,
        current_joints_deg=target["current_joints_deg"],
        required_calibration_id=target["calibration_id"],
        now_ns=stamp.monotonic_ns,
        config=config,
    )


def _depth_proposal(target: Mapping[str, Any], stamp: FrameStamp, config):
    quality = DepthQuality(
        valid_points=target["valid_points"],
        central_fraction=target["central_fraction"],
        center_d435_m=target["center_d435_m"],
        center_base_m=target["center_base_m"],
        mad_m=target["mad_m"],
        acceptable=target["acceptable"],
        reasons=tuple(target["reasons"]),
    )
    proposal = propose_refinement(
        target["identity_id"],
        quality,
        np.eye(4),
        stamp,
        stamp.monotonic_ns,
        target["step_index"],
        config,
        (target["calibration_id"],),
    )
    return quality, proposal


def run_active_view_replay(manifest_path: Path | str) -> ActiveViewReplayMetrics:
    path = Path(manifest_path).resolve()
    manifest = _read_manifest(path)
    config_raw = _mapping(manifest["config"], "config")
    poses = config_raw.get("observation_poses")
    if not isinstance(poses, list):
        raise ActiveViewReplayError("config observation_poses must be an array")
    if len(poses) > MAX_OBSERVATION_POSES:
        raise ActiveViewReplayError("active-view replay exceeds 64 observation poses")
    try:
        config = load_active_view_config_dict(config_raw)
    except (InvalidDataError, TypeError, ValueError) as exc:
        raise ActiveViewReplayError(f"invalid active-view replay config: {exc}") from exc

    frames = manifest["frames"]
    if not isinstance(frames, list) or not frames:
        raise ActiveViewReplayError("frames must be a non-empty array")
    if len(frames) > MAX_FRAMES:
        raise ActiveViewReplayError("active-view replay cannot exceed 10,000 frames")

    previous_timestamp = -1
    frame_ids: set[int] = set()
    identities: dict[str, int] = {}
    identity_switches = 0
    proposal_count = 0
    pose_expected = 0
    pose_correct = 0
    depth_frames = 0
    accepted_depth_frames = 0
    rejection_reasons: Counter[str] = Counter()

    for frame_index, raw_frame in enumerate(frames):
        frame_name = f"frames[{frame_index}]"
        frame = _mapping(raw_frame, frame_name)
        _exact_keys(frame, {"frame_id", "monotonic_ns", "targets"}, set(), frame_name)
        frame_id = frame["frame_id"]
        timestamp = frame["monotonic_ns"]
        if (
            isinstance(frame_id, bool)
            or not isinstance(frame_id, int)
            or frame_id < 0
            or frame_id in frame_ids
        ):
            raise ActiveViewReplayError("frame IDs must be unique non-negative integers")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= previous_timestamp:
            raise ActiveViewReplayError("frame timestamps must be strictly increasing")
        frame_ids.add(frame_id)
        previous_timestamp = timestamp
        targets = frame["targets"]
        if not isinstance(targets, list) or len(targets) > MAX_TARGETS_PER_FRAME:
            raise ActiveViewReplayError("each frame supports at most 256 targets")
        stamp = FrameStamp("active_view_replay", frame_id, timestamp)

        for target_index, raw_target in enumerate(targets):
            target_name = f"{frame_name}.targets[{target_index}]"
            target = _mapping(raw_target, target_name)
            mode = target.get("mode")
            common = {"mode", "track_key", "identity_id", "label", "calibration_id"}
            expected = {"expected_kind", "expected_pose_id", "expected_reason", "expected_translation_norm_m"}
            if mode == "coarse":
                required = common | {
                    "center_xy_m",
                    "covariance_xy_m2",
                    "samples_xy_m",
                    "current_joints_deg",
                    "expected_kind",
                }
                _exact_keys(target, required, expected, target_name)
            elif mode == "depth":
                required = common | {
                    "valid_points",
                    "central_fraction",
                    "center_d435_m",
                    "center_base_m",
                    "mad_m",
                    "acceptable",
                    "reasons",
                    "step_index",
                    "expected_kind",
                }
                _exact_keys(target, required, expected, target_name)
            else:
                raise ActiveViewReplayError(f"{target_name}.mode is invalid")
            _target_common(target, target_name, config.table_plane.calibration_id)

            track_key = target["track_key"]
            identity_id = target["identity_id"]
            if track_key in identities and identities[track_key] != identity_id:
                identity_switches += 1
            identities[track_key] = identity_id
            try:
                if mode == "coarse":
                    proposal = _coarse_proposal(target, stamp, config)
                    if "expected_pose_id" in target:
                        pose_expected += 1
                        if (
                            proposal.kind == target["expected_kind"]
                            and proposal.target_pose_id == target["expected_pose_id"]
                        ):
                            pose_correct += 1
                else:
                    depth_frames += 1
                    quality, proposal = _depth_proposal(target, stamp, config)
                    accepted_depth_frames += int(quality.acceptable)
            except (InvalidDataError, TypeError, ValueError) as exc:
                raise ActiveViewReplayError(f"invalid replay target {target_name}: {exc}") from exc

            if proposal.kind != target["expected_kind"]:
                raise ActiveViewReplayError(f"{target_name} expected proposal kind does not match")
            if "expected_reason" in target and proposal.reasons != (target["expected_reason"],):
                raise ActiveViewReplayError(f"{target_name} expected rejection reason does not match")
            if "expected_translation_norm_m" in target:
                if proposal.delta_base_m is None or not np.isclose(
                    np.linalg.norm(proposal.delta_base_m),
                    target["expected_translation_norm_m"],
                    atol=1e-12,
                ):
                    raise ActiveViewReplayError(f"{target_name} refinement clipping does not match")
            if proposal.kind == "none":
                rejection_reasons.update(proposal.reasons)
            else:
                proposal_count += 1

    pose_accuracy = 1.0 if pose_expected == 0 else pose_correct / pose_expected
    depth_rate = 0.0 if depth_frames == 0 else accepted_depth_frames / depth_frames
    return ActiveViewReplayMetrics(
        frame_count=len(frames),
        proposal_count=proposal_count,
        pose_selection_accuracy=pose_accuracy,
        depth_quality_acceptance_rate=depth_rate,
        identity_switches=identity_switches,
        rejection_reasons=dict(rejection_reasons),
        execution_proposals=0,
    )


def write_active_view_metrics_atomic(
    path: Path | str,
    metrics: ActiveViewReplayMetrics,
) -> None:
    destination = Path(path)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    payload = json.dumps(metrics.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(destination)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    metrics = run_active_view_replay(arguments.manifest)
    write_active_view_metrics_atomic(arguments.output, metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
