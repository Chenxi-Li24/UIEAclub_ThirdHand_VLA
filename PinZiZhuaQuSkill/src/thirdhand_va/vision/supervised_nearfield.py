"""Attach supervised RGB evidence to a frozen, measured bottle reference.

No robot control and no replacement of missing depth with projected values.
Geometry lives in nearfield_guard; this module owns frame/pose/anchor provenance.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from thirdhand_va.vision.nearfield_guard import create_reference, evaluate_reference


_ANCHOR_MAX_AGE_MS = 300_000


def add_reference_candidate(payload, *, frame, candidate, t_base_camera,
                            observation_height_m, bottle_diameter_m):
    result = dict(payload)
    if not result.get("supervised_base_candidate_valid") or candidate is None:
        return result
    try:
        reference = create_reference(
            frame, candidate, t_base_camera, result["base_xyz_m"], result["calibration_id"]
        )
    except (ValueError, TypeError, KeyError) as exc:
        result["nearfield_reference_error"] = str(exc)
        return result
    reference.update({
        "valid": True, "target_id": result["target_id"],
        "calibration_id": result["calibration_id"],
        "frame_id": result["frame_id"], "observed_at_ms": result["observed_at_ms"],
        "observation_height_base_m": observation_height_m,
        "bottle_diameter_m": bottle_diameter_m,
        "base_xyz_m": result["base_xyz_m"],
        "source_camera_xyz_m": result["camera_xyz_m"],
        "source_pixel_uv": result["pixel_uv"],
        "track_state": result.get("track_state"),
        "locked_detection_id": result.get("locked_detection_id"),
        "requested_ordinal": result.get("requested_ordinal"),
    })
    result["nearfield_reference_candidate"] = reference
    return result


def build_projection_observation(payload, *, frame, candidate, pose,
                                 t_base_camera, now_ms=None):
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    anchor = pose.get("supervised_anchor") or {}
    blockers = []
    if not anchor or not isinstance(anchor.get("reference"), dict):
        blockers.append("anchor_unapproved")
    if not anchor.get("trial_id") or anchor.get("trial_id") != pose.get("trial_id"):
        blockers.append("trial_mismatch")
    if anchor.get("target_id") != payload.get("target_id"):
        blockers.append("target_identity_changed")
    if anchor.get("calibration_id") != payload.get("calibration_id"):
        blockers.append("calibration_mismatch")
    age = now_ms - anchor.get("approved_at_ms", 0)
    if not 0 <= age <= _ANCHOR_MAX_AGE_MS:
        blockers.append("anchor_expired")
    frame_age = now_ms - payload["observed_at_ms"]
    if not 0 <= frame_age <= 300:
        blockers.append("frame_stale")
    translation = np.zeros(3)
    attachment = anchor.get("attachment")
    if attachment is not None:
        try:
            contact_xyz = np.asarray(attachment["contact_tcp_position_m"], dtype=float)
            contact_euler = np.asarray(attachment["contact_tcp_euler_rad"], dtype=float)
            xyz = np.asarray(pose["tcp_position_m"], dtype=float)
            euler = np.asarray(pose["tcp_euler_rad"], dtype=float)
            if any(v.shape != (3,) or not np.isfinite(v).all()
                   for v in (contact_xyz, contact_euler, xyz, euler)):
                raise ValueError("invalid attachment pose")
            angle_delta = np.arctan2(np.sin(euler-contact_euler), np.cos(euler-contact_euler))
            if np.max(np.abs(angle_delta)) > 0.12:
                blockers.append("orientation_changed")
            translation = xyz - contact_xyz
        except (KeyError, TypeError, ValueError):
            blockers.append("attachment_invalid")
    geometry: dict[str, Any] = {}
    if not blockers:
        try:
            geometry = evaluate_reference(
                frame, candidate, t_base_camera, anchor["reference"], translation
            )
        except (ValueError, TypeError, KeyError, IndexError):
            blockers.append("projection_reference_invalid")
    pose_blockers = payload.get("robot_pose_blockers", ["robot_pose_missing"])
    guard_blockers = list(dict.fromkeys(blockers + geometry.get("guard_blockers", [])))
    diagnostics = geometry.get("diagnostics", {})
    expected = None
    try:
        base = np.asarray(anchor["base_xyz_m"], dtype=float)
        if base.shape == (3,) and np.isfinite(base).all():
            expected = (base + translation).tolist()
    except (KeyError, TypeError, ValueError):
        guard_blockers.append("anchor_pose_invalid")
    return {
        "event": "bottle_projection_guard", "evidence_source": "rgb_fk_projection_guard",
        "trial_id": pose.get("trial_id"), "anchor_id": anchor.get("anchor_id"),
        "phase": pose.get("pending_phase") or pose.get("controller_phase"),
        "target_id": payload.get("target_id"),
        "calibration_id": payload.get("calibration_id"),
        "camera_serial": payload.get("camera_serial"),
        "registration_id": payload.get("registration_id"),
        "frame_id": frame.sequence, "captured_monotonic_ns": frame.monotonic_ns,
        "observed_at_ms": payload["observed_at_ms"], "emitted_at_ms": now_ms,
        "robot_state_ts": payload.get("robot_state_ts"),
        "robot_pose_blockers": pose_blockers,
        "rgb_observation_valid": not blockers and geometry.get("rgb_observation_valid") is True,
        "projection_guard_valid": (not guard_blockers and not pose_blockers
                                   and expected is not None
                                   and geometry.get("projection_guard_valid") is True),
        "guard_blockers": guard_blockers,
        "expected_anchor_base_xyz_m": expected,
        "projected_anchor_camera_xyz_m": diagnostics.get("expected_center_camera_xyz_m"),
        "pixel_uv": diagnostics.get("expected_center_uv"),
        "raw_depth_used": False, "diagnostics": diagnostics,
        "robot_control_enabled": False, "execution_enabled": False,
    }
