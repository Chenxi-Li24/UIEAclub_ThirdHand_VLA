"""Fail-closed compatibility boundary for the reusable ThirdHand Vision SDK.

This module converts immutable runtime records to SDK records and SDK results
back to the existing browser event contract.  It owns no devices, models,
threads, network clients, or robot interfaces.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from thirdhand_vision import (
    CameraCalibrationRef,
    FrameBundle,
    FrameStamp,
    FusionCalibration,
    PerceptionInstance,
    PerceptionResult,
)
from thirdhand_vision.core.camera import PinholeCamera, SeucmCamera


def _non_negative_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be a non-negative integer")
    result = int(value)
    if result < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return result


def _finite_transform(value: Any, name: str) -> np.ndarray:
    transform = np.asarray(value, dtype=float)
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError(f"{name} must be a finite 4x4 transform")
    return np.array(transform, copy=True)


def runtime_calibration_to_sdk(
    calibration: Any,
    *,
    t_output_from_lumos: Any,
) -> FusionCalibration:
    """Copy a validated runtime calibration bundle into SDK contracts."""

    required = ("d435", "lumos", "t_lumos_from_d435", "calibration")
    if calibration is None or any(not hasattr(calibration, name) for name in required):
        raise ValueError("runtime calibration bundle is incomplete")
    runtime_ref = calibration.calibration
    ref = CameraCalibrationRef(
        calibration_id=runtime_ref.calibration_id,
        validated=runtime_ref.validated,
        reprojection_rmse_px=runtime_ref.reprojection_rmse_px,
    )
    d435 = calibration.d435
    lumos = calibration.lumos
    return FusionCalibration(
        d435=PinholeCamera(
            fx=d435.fx,
            fy=d435.fy,
            cx=d435.cx,
            cy=d435.cy,
            width=d435.width,
            height=d435.height,
        ),
        lumos=SeucmCamera(
            fx=lumos.fx,
            fy=lumos.fy,
            cx=lumos.cx,
            cy=lumos.cy,
            alpha=lumos.alpha,
            beta=lumos.beta,
            width=lumos.width,
            height=lumos.height,
        ),
        t_lumos_from_d435=_finite_transform(
            calibration.t_lumos_from_d435, "t_lumos_from_d435"
        ),
        t_output_from_lumos=_finite_transform(
            t_output_from_lumos, "t_output_from_lumos"
        ),
        ref=ref,
    )


def frame_pair_to_sdk(
    pair: Any,
    calibration: FusionCalibration | None,
    *,
    canonical_rgb_source: str,
    metric_depth_source: str,
) -> FrameBundle:
    """Convert a pair after checking declared source roles and calibration sizes."""

    if pair is None or not hasattr(pair, "rgb"):
        raise ValueError("runtime frame pair is incomplete")
    for value, name in (
        (canonical_rgb_source, "canonical_rgb_source"),
        (metric_depth_source, "metric_depth_source"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty source role")
    if canonical_rgb_source == metric_depth_source:
        raise ValueError("RGB and depth source roles must be distinct")
    rgb_stamp = pair.rgb.stamp
    if rgb_stamp.source != canonical_rgb_source:
        raise ValueError("frame does not use the required canonical RGB source")
    stamp = FrameStamp(
        rgb_stamp.source,
        _non_negative_integer(rgb_stamp.frame_id, "rgb frame_id"),
        _non_negative_integer(rgb_stamp.monotonic_ns, "rgb monotonic_ns"),
    )
    depth_m = None
    depth_stamp = None
    if pair.depth is not None:
        raw_depth = np.asarray(pair.depth.depth_z_m)
        if raw_depth.ndim != 2 or not np.issubdtype(raw_depth.dtype, np.number):
            raise ValueError("depth image must be a numeric 2D array")
        depth_m = np.array(raw_depth, dtype=np.float32, copy=True)
        if np.isinf(depth_m).any():
            raise ValueError("depth image cannot contain infinity")
        finite = np.isfinite(depth_m)
        if np.any(depth_m[finite] < 0.0):
            raise ValueError("depth image cannot contain negative values")
        depth_m[depth_m == 0.0] = np.nan
        runtime_depth_stamp = pair.depth.stamp
        if runtime_depth_stamp.source != metric_depth_source:
            raise ValueError("frame does not use the required metric depth source")
        depth_stamp = FrameStamp(
            runtime_depth_stamp.source,
            _non_negative_integer(runtime_depth_stamp.frame_id, "depth frame_id"),
            _non_negative_integer(runtime_depth_stamp.monotonic_ns, "depth monotonic_ns"),
        )
    if calibration is not None and not isinstance(calibration, FusionCalibration):
        raise ValueError("calibration must be an SDK FusionCalibration or None")
    rgb_image = np.asarray(pair.rgb.image_rgb)
    if calibration is not None:
        if rgb_image.shape[:2] != (calibration.lumos.height, calibration.lumos.width):
            raise ValueError("RGB image does not match Lumos calibration dimensions")
        if depth_m is not None and depth_m.shape != (
            calibration.d435.height,
            calibration.d435.width,
        ):
            raise ValueError("depth image does not match D435 calibration dimensions")
    reasons = tuple(getattr(pair, "reasons", ()))
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise ValueError("frame reasons must contain non-empty strings")
    frame_skew_ns = getattr(pair, "frame_skew_ns", None)
    if frame_skew_ns is not None:
        frame_skew_ns = _non_negative_integer(frame_skew_ns, "frame_skew_ns")
    fusion_ns = _non_negative_integer(
        getattr(pair, "fusion_monotonic_ns", stamp.monotonic_ns),
        "fusion_monotonic_ns",
    )
    return FrameBundle(
        rgb=pair.rgb.image_rgb,
        stamp=stamp,
        depth_m=depth_m,
        depth_stamp=depth_stamp,
        calibration=calibration,
        metadata={
            "fusion_monotonic_ns": fusion_ns,
            "frame_skew_ns": frame_skew_ns,
            "reasons": reasons,
        },
    )


_IDENTITY_MEMORY_KEYS = (
    "hits",
    "work_prototype_count",
    "stable_prototype_count",
    "appearance_similarity",
    "association_cost",
    "association_reason",
)


def _identity_memory(annotations: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = annotations.get("identity_memory")
    if not isinstance(raw, Mapping):
        return None
    result = {name: raw.get(name) for name in _IDENTITY_MEMORY_KEYS}
    for name in _IDENTITY_MEMORY_KEYS[:3]:
        result[name] = _non_negative_integer(result[name], f"identity_memory.{name}")
    for name in ("appearance_similarity", "association_cost"):
        value = result[name]
        if value is not None:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"identity_memory.{name} must be finite or null")
            result[name] = value
    reason = result["association_reason"]
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise ValueError("identity_memory.association_reason must be non-empty or null")
    return result


def _serialize_instance(instance: PerceptionInstance) -> dict[str, Any]:
    annotations = instance.annotations
    registered = annotations.get("registered_depth_points", 0)
    registered = _non_negative_integer(registered, "registered_depth_points")
    return {
        "detection_id": instance.detection.detection_id,
        "identity_id": instance.identity_id,
        "identity_status": instance.identity_status,
        "identity_memory": _identity_memory(annotations),
        "label": instance.detection.label,
        "score": instance.detection.score,
        "bbox_xyxy": instance.detection.bbox_xyxy.tolist(),
        "pose": None if instance.pose is None else instance.pose.to_dict(),
        "registered_depth_points": registered,
        "actionable": False,
        "reasons": list(instance.reasons),
    }


def sdk_result_to_detection_event(
    result: PerceptionResult,
    *,
    ts_ms: int,
) -> dict[str, Any]:
    """Serialize an SDK result into the existing fail-closed browser event."""

    if not isinstance(result, PerceptionResult):
        raise ValueError("result must be a PerceptionResult")
    timestamp = _non_negative_integer(ts_ms, "ts_ms")
    return {
        "type": "detection_result",
        "ts": timestamp,
        "frame_id": result.frame_id,
        "monotonic_ns": result.monotonic_ns,
        "targets": [_serialize_instance(item) for item in result.instances],
        "blockers": list(result.blockers),
        "robot_execution_enabled": False,
        "active_view_execution_enabled": False,
    }


def _frames_by_id(frames: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    indexed: dict[int, Mapping[str, Any]] = {}
    for frame in frames:
        if not isinstance(frame, Mapping):
            raise ValueError("replay frames must be objects")
        frame_id = _non_negative_integer(frame.get("frame_id"), "frame_id")
        if frame_id in indexed:
            raise ValueError("replay frame IDs must be unique")
        indexed[frame_id] = frame
    return indexed


def _target_map(frame: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    targets = frame.get("targets")
    if not isinstance(targets, list):
        raise ValueError("replay targets must be a list")
    mapped: dict[str, Mapping[str, Any]] = {}
    detection_ids: set[int] = set()
    for target in targets:
        if not isinstance(target, Mapping):
            raise ValueError("replay target must be an object")
        detection_id = _non_negative_integer(target.get("detection_id"), "detection_id")
        if detection_id in detection_ids:
            raise ValueError("detection IDs must be unique within each frame")
        detection_ids.add(detection_id)
        correspondence_id = target.get("correspondence_id")
        if (
            not isinstance(correspondence_id, str)
            or not correspondence_id.strip()
            or len(correspondence_id) > 128
        ):
            raise ValueError("replay targets require a non-empty correspondence_id")
        if correspondence_id in mapped:
            raise ValueError("correspondence_id values must be unique within each frame")
        mapped[correspondence_id] = target
    return mapped


def _identity_switches(frames: Sequence[Mapping[str, Any]]) -> int:
    previous: dict[str, Any] = {}
    switches = 0
    for frame in sorted(frames, key=lambda value: int(value["frame_id"])):
        current = {
            correspondence_id: target.get("identity_id")
            for correspondence_id, target in _target_map(frame).items()
        }
        for correspondence_id, identity_id in current.items():
            if correspondence_id in previous and previous[correspondence_id] != identity_id:
                switches += 1
        previous.update(current)
    return switches


def _descriptor_delta(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    if "descriptor" not in left or "descriptor" not in right:
        raise ValueError("replay descriptors are required for measured parity")
    first = np.asarray(left.get("descriptor"), dtype=float)
    second = np.asarray(right.get("descriptor"), dtype=float)
    if (
        first.ndim != 1
        or first.shape != second.shape
        or not np.isfinite(first).all()
        or not np.isfinite(second).all()
    ):
        raise ValueError("replay descriptors must be matching finite vectors")
    norms = float(np.linalg.norm(first) * np.linalg.norm(second))
    if norms <= 0.0:
        raise ValueError("replay descriptor norms must be positive")
    return float(abs(1.0 - np.dot(first, second) / norms))


def compare_replay_frames(
    legacy: Sequence[Mapping[str, Any]],
    sdk: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    """Compare replays using required persistent correspondences and descriptors."""

    required_thresholds = {
        "identity_switch_delta_max",
        "pose_rmse_m_max",
        "covariance_abs_max",
        "descriptor_cosine_delta_max",
    }
    if set(thresholds) != required_thresholds:
        raise ValueError("replay thresholds must use the exact declared keys")
    limits = {name: float(value) for name, value in thresholds.items()}
    if any(not math.isfinite(value) or value < 0.0 for value in limits.values()):
        raise ValueError("replay thresholds must be finite and non-negative")
    left = _frames_by_id(legacy)
    right = _frames_by_id(sdk)
    if set(left) != set(right):
        raise ValueError("replay streams must contain identical frame IDs")

    detection_count_mismatches = 0
    label_mismatches = 0
    blocker_mismatches = 0
    pose_differences: list[float] = []
    covariance_max = 0.0
    descriptor_max = 0.0
    descriptor_pairs = 0
    for frame_id in sorted(left):
        legacy_frame = left[frame_id]
        sdk_frame = right[frame_id]
        legacy_targets = _target_map(legacy_frame)
        sdk_targets = _target_map(sdk_frame)
        detection_count_mismatches += int(len(legacy_targets) != len(sdk_targets))
        blocker_mismatches += int(legacy_frame.get("blockers", []) != sdk_frame.get("blockers", []))
        for correspondence_id in sorted(set(legacy_targets) | set(sdk_targets)):
            if correspondence_id not in legacy_targets or correspondence_id not in sdk_targets:
                label_mismatches += 1
                continue
            legacy_target = legacy_targets[correspondence_id]
            sdk_target = sdk_targets[correspondence_id]
            label_mismatches += int(legacy_target.get("label") != sdk_target.get("label"))
            descriptor_max = max(descriptor_max, _descriptor_delta(legacy_target, sdk_target))
            descriptor_pairs += 1
            legacy_pose = legacy_target.get("pose")
            sdk_pose = sdk_target.get("pose")
            if legacy_pose is None and sdk_pose is None:
                continue
            if not isinstance(legacy_pose, Mapping) or not isinstance(sdk_pose, Mapping):
                pose_differences.append(float("inf"))
                continue
            legacy_xyz = np.asarray(legacy_pose.get("xyz_m"), dtype=float)
            sdk_xyz = np.asarray(sdk_pose.get("xyz_m"), dtype=float)
            legacy_cov = np.asarray(legacy_pose.get("covariance_m2"), dtype=float)
            sdk_cov = np.asarray(sdk_pose.get("covariance_m2"), dtype=float)
            if (
                legacy_xyz.shape != (3,)
                or sdk_xyz.shape != (3,)
                or not np.isfinite(legacy_xyz).all()
                or not np.isfinite(sdk_xyz).all()
            ):
                raise ValueError("replay poses must contain finite xyz_m vectors")
            if (
                legacy_cov.shape != (3, 3)
                or sdk_cov.shape != (3, 3)
                or not np.isfinite(legacy_cov).all()
                or not np.isfinite(sdk_cov).all()
            ):
                raise ValueError("replay poses must contain finite 3x3 covariance")
            pose_differences.extend((legacy_xyz - sdk_xyz).tolist())
            covariance_max = max(covariance_max, float(np.max(np.abs(legacy_cov - sdk_cov))))

    pose_rmse = (
        0.0
        if not pose_differences
        else float(np.sqrt(np.mean(np.square(np.asarray(pose_differences, dtype=float)))))
    )
    switch_delta = abs(_identity_switches(legacy) - _identity_switches(sdk))
    metrics = {
        "paired_frames": len(left),
        "detection_count_mismatches": detection_count_mismatches,
        "label_mismatches": label_mismatches,
        "blocker_mismatches": blocker_mismatches,
        "identity_switch_delta": switch_delta,
        "pose_rmse_m": pose_rmse,
        "covariance_abs_max": covariance_max,
        "descriptor_pairs": descriptor_pairs,
        "descriptor_cosine_delta": descriptor_max,
    }
    failures = []
    for exact_name in ("detection_count_mismatches", "label_mismatches", "blocker_mismatches"):
        if metrics[exact_name] != 0:
            failures.append(exact_name)
    if descriptor_pairs == 0:
        failures.append("descriptor_pairs_missing")
    threshold_metrics = {
        "identity_switch_delta_max": "identity_switch_delta",
        "pose_rmse_m_max": "pose_rmse_m",
        "covariance_abs_max": "covariance_abs_max",
        "descriptor_cosine_delta_max": "descriptor_cosine_delta",
    }
    for limit_name, metric_name in threshold_metrics.items():
        if metrics[metric_name] > limits[limit_name]:
            failures.append(limit_name)
    return {
        "schema_version": 1,
        "metrics": metrics,
        "failures": failures,
        "passed": not failures,
    }


__all__ = [
    "compare_replay_frames",
    "frame_pair_to_sdk",
    "runtime_calibration_to_sdk",
    "sdk_result_to_detection_event",
]
