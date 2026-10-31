"""Convert measured source units while preserving the actual raw state separately."""
import copy
import datetime as dt
import math
import time


def _vector(value, size, scale=1.0):
    if not isinstance(value, list) or len(value) != size or any(type(item) not in (int, float) or not math.isfinite(item) for item in value):
        return None
    return [item * scale for item in value]


def _json_source(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": str(value)}
    if isinstance(value, dict):
        return {key: _json_source(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_source(item) for item in value]
    return copy.deepcopy(value)


def normalize_robot_state(message, *, monotonic_ns=None, received_at=None, versions=None):
    if not isinstance(message, dict) or message.get("type") != "robot_state":
        raise ValueError("Measured robot_state required")
    received_at = received_at or dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    versions = versions or {}
    flags = []
    captured_at = message.get("captured_at")
    if not isinstance(captured_at, str):
        source_ms = message.get("ts")
        if type(source_ms) in (int, float) and math.isfinite(source_ms):
            try:
                captured_at = dt.datetime.fromtimestamp(source_ms / 1000, dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            except (OverflowError, ValueError, OSError):
                captured_at = received_at
                flags.append("CAPTURE_TIME_ESTIMATED")
        else:
            captured_at = received_at
            flags.append("CAPTURE_TIME_ESTIMATED")
    raw_joints = message.get("joints_deg", message.get("joints"))
    positions = _vector(raw_joints, 6, math.pi / 180)
    if positions is None:
        # Preserve the invalid dimensionality for invalid_samples; never fill
        # missing measured joints with zeroes or a browser's desired pose.
        positions = [item * math.pi / 180 if type(item) in (int, float) and math.isfinite(item) else None for item in raw_joints] if isinstance(raw_joints, list) else None
        flags.append("INVALID_JOINT_POSITION")
    measured = {"jointPositionRad": positions,
                "jointVelocityRadS": _vector(message.get("velocities_deg_s", message.get("velocities")), 6, math.pi / 180),
                "jointCurrentA": _vector(message.get("currents_a"), 6),
                "jointTorqueNm": _vector(message.get("torques_nm", message.get("torques")), 6),
                "jointTemperatureC": _vector(message.get("temperatures_c"), 6)}
    availability = {name: value is not None and (name != "jointPositionRad" or len(value) == 6 and all(item is not None for item in value)) for name, value in measured.items()}
    connected, moving = message.get("connected"), message.get("moving")
    availability["sdkConnected"], availability["moving"] = type(connected) is bool, type(moving) is bool
    if type(connected) is not bool:
        flags.append("SDK_STATE_UNKNOWN")
    if type(moving) is not bool:
        flags.append("MOVING_STATE_UNKNOWN")
    extra = {"rawState": _json_source(message), "sourceVersions": dict(versions)}
    target = _vector(message.get("target_joints_deg"), 6, math.pi / 180)
    if target is not None:
        extra["target"] = {"jointPositionRad": target, "kind": "source_reported_target"}
    tcp_position = tcp_orientation = None
    frame = message.get("pose_frame")
    if frame == "robot_flange":
        extra["flangePositionM"] = _vector(message.get("flange_position_m"), 3)
        extra["flangeOrientationEulerRad"] = _vector(message.get("flange_euler_rad"), 3)
        extra["poseFrameId"] = frame
    elif frame == "tool_tcp":
        tcp_position = _vector(message.get("tcp_position_m"), 3)
        tcp_orientation = _vector(message.get("tcp_orientation_xyzw"), 4)
    availability["tcpPositionM"], availability["tcpOrientationXyzw"] = tcp_position is not None, tcp_orientation is not None
    quality = message.get("clock_quality", "estimated")
    if quality not in ("synchronized", "estimated", "unreliable"):
        quality = "unreliable"
    result = {"capturedAt": captured_at, "monotonicNs": str(time.monotonic_ns() if monotonic_ns is None else monotonic_ns),
              "clockQuality": quality, **measured, "fieldAvailability": availability,
              "tcpPositionM": tcp_position, "tcpOrientationXyzw": tcp_orientation,
              "tcpFrameId": frame if tcp_position is not None else None,
              "toolVersion": versions.get("tool", versions.get("toolVersion")), "calibrationVersion": versions.get("calibration", versions.get("calibrationVersion")),
              "sdkConnected": connected if type(connected) is bool else False,
              "moving": moving if type(moving) is bool else False, "qualityFlags": flags, "extra": extra}
    if type(message.get("state_age_ms")) is int and message["state_age_ms"] >= 0:
        result["stateAgeMs"] = message["state_age_ms"]
    return result
