from __future__ import annotations

import time


def build_diagnostics(*, target, command, debug, error, robot_snapshot=None):
    debug = debug or {}
    rows = []
    found = bool(getattr(target, "found", False))
    target_mode = debug.get("target_3d_mode")
    rows.append(_row("VisionTracker", "ok" if found and error is None else "bad", _vision_text(target, error)))
    rows.append(_row("TargetLock", "ok" if found else "bad", _target_text(target, debug)))
    rows.append(_row("DepthEstimator", _depth_level(debug), _depth_estimator_text(debug)))
    rows.append(_row("TargetProjector", _target3d_level(target_mode), _target3d_text(debug)))
    rows.append(_row("HandEyeProjector", "ok" if debug.get("handeye_ok") else "warn", _handeye_text(debug)))
    rows.append(_row("DistancePolicy", "warn" if target_mode == "virtual3d" else ("ok" if debug.get("distance_state") else "bad"), _distance_text(debug)))
    rows.append(_row("IKBackend", "ok" if getattr(command, "target_found", False) else "bad", _ik_text(command, debug)))
    rows.append(_row("MotionCommand", _motion_level(command, robot_snapshot), _motion_text(command, robot_snapshot)))
    rows.append(_row("RobotAdapter", "ok" if _robot_ok(robot_snapshot) else "warn", _robot_text(robot_snapshot)))
    rows.append(_row("Next", "info", _suggestion(rows, command, debug, error, robot_snapshot)))
    return rows


def _row(name, level, detail):
    return {"name": name, "level": level, "ok": level in {"ok", "info"}, "detail": detail}


def _vision_text(target, error):
    if error:
        return f"camera/vision error: {error}"
    if getattr(target, "found", False):
        return f"locked target: {getattr(target, 'kind', '-')}"
    return f"no stable target: {getattr(target, 'kind', 'none')}"


def _target_text(target, debug):
    if not getattr(target, "found", False):
        rejected = debug.get("rejected")
        return "no stable target" + (f", rejected: {rejected}" if rejected else "")
    err_x = float(getattr(target, "u", 0.0)) - float(getattr(target, "w", 0.0)) / 2.0
    err_y = float(getattr(target, "v", 0.0)) - float(getattr(target, "h", 0.0)) / 2.0
    return f"image error x={err_x:+.0f}px y={err_y:+.0f}px, score={float(getattr(target, 'score', 0.0)):.2f}"


def _target3d_text(debug):
    mode = debug.get("target_3d_mode", "none")
    xyz = debug.get("target_xyz_m")
    if not isinstance(xyz, (list, tuple)) or len(xyz) != 3:
        return "no 3D target yet"
    label = "real depth" if mode == "depth3d" else "virtual depth"
    return f"{label} xyz=({float(xyz[0]):+.2f}, {float(xyz[1]):+.2f}, {float(xyz[2]):+.2f})m"


def _handeye_text(debug):
    source = debug.get("handeye_source", "-")
    reason = debug.get("handeye_reason")
    camera_xyz = debug.get("target_camera_xyz_m")
    base_xyz = debug.get("target_xyz_m")
    if debug.get("handeye_ok") and isinstance(base_xyz, (list, tuple)) and len(base_xyz) == 3:
        return f"{source}: base xyz=({float(base_xyz[0]):+.2f}, {float(base_xyz[1]):+.2f}, {float(base_xyz[2]):+.2f})m"
    if isinstance(camera_xyz, (list, tuple)) and len(camera_xyz) == 3:
        return f"{source}: using camera xyz fallback, reason={reason or '-'}"
    return f"{source}: no hand-eye projection, reason={reason or '-'}"


def _depth_estimator_text(debug):
    depth = debug.get("estimated_depth_m", debug.get("distance_depth_m"))
    source = debug.get("estimated_depth_source", debug.get("distance_depth_source", "-"))
    confidence = float(debug.get("estimated_depth_confidence", debug.get("distance_depth_confidence", 0.0)) or 0.0)
    metric = "real metric" if debug.get("estimated_depth_metric") else "estimated"
    if depth is None:
        return "no depth estimate"
    return f"{source}: {float(depth):.2f}m, conf={confidence:.2f}, {metric}"


def _depth_level(debug):
    source = debug.get("estimated_depth_source", debug.get("distance_depth_source"))
    if source in {"rgbd", "fused"}:
        return "ok"
    if source in {"mono_bbox", "fallback"}:
        return "warn"
    return "bad"


def _target3d_level(mode):
    if mode == "depth3d":
        return "ok"
    if mode == "virtual3d":
        return "warn"
    return "bad"


def _distance_text(debug):
    state = debug.get("distance_state", "-")
    depth = debug.get("distance_depth_m")
    depth_text = "-" if depth is None else f"{float(depth):.2f}m"
    source = debug.get("distance_depth_source", "-")
    valid = "real depth" if debug.get("distance_depth_valid") else "estimated depth"
    return f"{state}, depth={depth_text}, source={source}, {valid}"


def _ik_text(command, debug):
    source = getattr(command, "source", debug.get("control_source", "-"))
    if getattr(command, "target_found", False):
        return f"IK output OK: {source}"
    return f"no IK motion output: {source}"


def _robot_ok(snapshot):
    return bool(snapshot and snapshot.connected and snapshot.state_ready)


def _motion_level(command, snapshot):
    if not getattr(command, "target_found", False):
        return "bad"
    if snapshot is None or not snapshot.joints_deg:
        return "warn"
    delta = _max_joint_delta(command.joints_deg, snapshot.joints_deg)
    if delta < 0.05:
        return "warn"
    return "ok"


def _motion_text(command, snapshot):
    if not getattr(command, "target_found", False):
        return "no q_target from controller"
    if snapshot is None or not snapshot.joints_deg:
        return "q_target exists, but live robot joints are unavailable"
    delta = _max_joint_delta(command.joints_deg, snapshot.joints_deg)
    moving = "robot moving" if snapshot.moving else "robot idle"
    return f"max |q_target-current| = {delta:.2f} deg, {moving}"


def _max_joint_delta(target, current):
    if not target or not current:
        return 0.0
    pairs = list(zip(target[:6], current[:6]))
    if not pairs:
        return 0.0
    return max(abs(float(a) - float(b)) for a, b in pairs)


def _robot_text(snapshot):
    if snapshot is None:
        return "robot state not read"
    age = time.time() - float(snapshot.last_event_at or 0.0) if snapshot.last_event_at else 999.0
    state = snapshot.state_name or "-"
    moving = "运动中" if snapshot.moving else "空闲"
    if not snapshot.connected:
        return "Robot Service is not connected"
    if not snapshot.state_ready:
        return "connected, but no 6-joint state yet"
    moving = "MOVING" if snapshot.moving else "IDLE"
    return f"{state} / {moving}, state age {age:.1f}s"


def _suggestion(rows, command, debug, error, snapshot):
    if error:
        return "check vision service 3100 or camera stream first"
    if not any(row["name"] == "TargetLock" and row["ok"] for row in rows):
        return "stand in view and wait for a stable lock point"
    if debug.get("target_3d_mode") == "virtual3d":
        return "no reliable RGB-D now; using estimated 3D + Mink follow"
    if str(getattr(command, "source", "")).startswith("mink_failed"):
        return "IK failed; check Mink/URDF or target outside workspace"
    if snapshot is not None and not _robot_ok(snapshot):
        return "robot state incomplete; check Robot Service 3000"
    if getattr(command, "target_found", False):
        return "pipeline OK; compare q_target with robot motion"
    return "check the first failed row above"
