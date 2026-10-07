from __future__ import annotations

from dataclasses import dataclass
import math
import time

from ..filters import clamp


@dataclass
class DistanceAwareCommand:
    state: str
    posture_joints_deg: list[float]
    depth_m: float | None
    depth_valid: bool
    reason: str
    depth_source: str = "none"
    depth_confidence: float = 0.0


class DistanceAwarePosturePolicy:
    """Turn person depth state into a whole-arm posture bias."""

    def __init__(self, config):
        options = config.get("distance_follow", {})
        robot = config.get("robot", {})
        self.enabled = bool(options.get("enabled", True))
        self.desired_depth_m = float(options.get("desired_depth_m", 0.85))
        self.deadband_m = float(options.get("deadband_m", 0.15))
        self.too_close_m = float(options.get("too_close_m", 0.55))
        self.far_depth_m = float(options.get("far_depth_m", 1.15))
        self.curious_depth_m = float(options.get("curious_depth_m", 1.65))
        self.depth_lost_far_reach_after_s = float(options.get("depth_lost_far_reach_after_s", 0.40))
        self.posture_step_deg = float(options.get("posture_step_deg", 0.35))
        self.active_joint_indices = [int(v) for v in options.get("active_joint_indices", [1, 2, 4])]
        self.home_pose = [float(v) for v in robot.get("home_joints_deg") or [0, 0, 0, 0, 0, 0]]
        self.far_reach_pose = self._pose(options.get("far_reach_pose_deg"), [0.0, 6.0, -8.0, 0.0, 0.0, 0.0])
        self.curious_reach_pose = self._pose(options.get("curious_reach_pose_deg"), self.far_reach_pose)
        self.hold_pose = self._pose(options.get("hold_pose_deg"), self.home_pose)
        self.retract_pose = self._pose(options.get("retract_pose_deg"), [0.0, -2.0, -3.0, -6.0, 0.0, 0.0])
        self.joint_limits = robot.get(
            "joint_limits_deg",
            [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
        )
        self._last_depth_seen_at = None
        self.last_command = DistanceAwareCommand("disabled", list(self.home_pose), None, False, "disabled")

    def reset(self):
        self._last_depth_seen_at = None
        self.last_command = DistanceAwareCommand("disabled", list(self.home_pose), None, False, "disabled")

    def update(self, joints, target, estimated_depth=None):
        current = [float(v) for v in joints]
        if not self.enabled:
            return DistanceAwareCommand("disabled", current, None, False, "disabled")

        depth_m = self._estimated_depth(target, estimated_depth)
        depth_valid = depth_m is not None and bool(getattr(estimated_depth, "metric", False) or getattr(target, "depth_valid", False))
        depth_source = str(getattr(estimated_depth, "source", "target" if depth_m is not None else "none"))
        depth_confidence = float(getattr(estimated_depth, "confidence", 1.0 if depth_valid else 0.0))
        now = time.time()
        if depth_m is not None and depth_confidence >= 0.10:
            self._last_depth_seen_at = now
            state = self._state_for_depth(depth_m)
            posture = self._posture_for_state(state)
            reason = "depth_estimated"
        else:
            lost_for = None if self._last_depth_seen_at is None else now - self._last_depth_seen_at
            if self._last_depth_seen_at is None or lost_for >= self.depth_lost_far_reach_after_s:
                state = "depth_invalid_far_reach"
                posture = list(self.far_reach_pose)
            else:
                state = "depth_recent_hold"
                posture = list(self.last_command.posture_joints_deg)
            reason = "depth_invalid"

        command = DistanceAwareCommand(
            state,
            self._rate_limit_posture(current, posture),
            depth_m,
            depth_valid,
            reason,
            depth_source,
            depth_confidence,
        )
        self.last_command = command
        return command

    def _state_for_depth(self, depth_m):
        if depth_m <= self.too_close_m:
            return "too_close_retract"
        if depth_m < self.desired_depth_m - self.deadband_m:
            return "near_retract"
        if depth_m >= self.curious_depth_m:
            return "curious_reach"
        if depth_m > max(self.far_depth_m, self.desired_depth_m + self.deadband_m):
            return "far_forward"
        return "hold_distance"

    def _posture_for_state(self, state):
        if state in {"too_close_retract", "near_retract"}:
            return list(self.retract_pose)
        if state == "curious_reach":
            return list(self.curious_reach_pose)
        if state == "far_forward":
            return list(self.far_reach_pose)
        return list(self.hold_pose)

    def apply_bias(self, joints, command):
        out = [float(v) for v in joints]
        for index in self.active_joint_indices:
            if 0 <= index < 6:
                out[index] = command.posture_joints_deg[index]
        return self._clamp(out)

    def _rate_limit_posture(self, current, desired):
        out = list(current)
        for index in self.active_joint_indices:
            if 0 <= index < 6:
                out[index] = current[index] + clamp(desired[index] - current[index], -self.posture_step_deg, self.posture_step_deg)
        return self._clamp(out)

    def _clamp(self, joints):
        out = [float(v) for v in joints]
        for index, limits in enumerate(self.joint_limits[:6]):
            try:
                lo, hi = float(limits[0]), float(limits[1])
            except Exception:
                continue
            out[index] = clamp(out[index], lo, hi)
        return out

    def _depth(self, target):
        value = getattr(target, "depth_m", None)
        if value is None:
            xyz = getattr(target, "xyz_m", None)
            if isinstance(xyz, (list, tuple)) and len(xyz) == 3:
                value = xyz[2]
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number > 0.0 else None

    def _estimated_depth(self, target, estimated_depth):
        if estimated_depth is not None:
            try:
                number = float(estimated_depth.depth_m)
            except (TypeError, ValueError):
                number = None
            if number is not None and math.isfinite(number) and number > 0.0:
                return number
        return self._depth(target)

    @staticmethod
    def _pose(value, fallback):
        if isinstance(value, (list, tuple)) and len(value) == 6:
            try:
                return [float(v) for v in value]
            except (TypeError, ValueError):
                pass
        return [float(v) for v in fallback]
