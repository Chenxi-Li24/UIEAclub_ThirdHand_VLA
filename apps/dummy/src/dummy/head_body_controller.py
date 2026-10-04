from __future__ import annotations

from .filters import clamp


class HeadBodyLookController:
    """Experimental 2D gaze controller with head-first, body-follow behavior."""

    def __init__(self, config):
        options = config.get("head_body_follow", {})
        self.head_yaw_joint = int(options.get("head_yaw_joint_index", 3))
        self.head_pitch_joint = int(options.get("head_pitch_joint_index", 4))
        self.roll_joint = int(options.get("roll_joint_index", 5))
        self.body_joints = [int(index) for index in options.get("body_joint_indices", [0, 1, 2])]

        self.deadzone = float(options.get("deadzone_px", 18))
        self.k_head_yaw = float(options.get("k_head_yaw_deg_per_px", -0.018))
        self.k_head_pitch = float(options.get("k_head_pitch_deg_per_px", -0.016))
        self.k_body_yaw = float(options.get("k_body_yaw_deg_per_px", -0.0025))

        self.max_head_step = float(options.get("max_head_step_deg", 1.0))
        self.max_body_step = float(options.get("max_body_step_deg", 0.2))
        self.max_roll_step = float(options.get("max_roll_step_deg", 0.2))
        self.head_comfort = float(options.get("head_comfort_deg", 8.0))
        self.head_recentering_gain = float(options.get("head_recentering_gain", 0.25))
        self.roll_neutral = float(options.get("roll_neutral_deg", 0.0))

        self.joint_limits = config.get(
            "robot", {}
        ).get("joint_limits_deg", [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]])
        self.base = None
        self.last_error_px = (0.0, 0.0)

    def reset_base(self, joints):
        self.base = list(joints)
        self.last_error_px = (0.0, 0.0)

    def target_for(self, joints, target):
        if self.base is None:
            self.reset_base(joints)

        out = [float(value) for value in joints]
        if not getattr(target, "found", False):
            return list(joints)

        ex = float(target.u) - float(target.w) / 2.0
        ey = float(target.v) - float(target.h) / 2.0
        self.last_error_px = (ex, ey)

        if abs(ex) > self.deadzone:
            out[self.head_yaw_joint] += clamp(
                self.k_head_yaw * ex,
                -self.max_head_step,
                self.max_head_step,
            )
        if abs(ey) > self.deadzone:
            out[self.head_pitch_joint] += clamp(
                self.k_head_pitch * ey,
                -self.max_head_step,
                self.max_head_step,
            )

        yaw_offset = out[self.head_yaw_joint] - self.base[self.head_yaw_joint]
        if abs(yaw_offset) > self.head_comfort and 0 in self.body_joints:
            body_step = clamp(self.k_body_yaw * ex, -self.max_body_step, self.max_body_step)
            out[0] += body_step
            out[self.head_yaw_joint] += clamp(
                self.base[self.head_yaw_joint] - out[self.head_yaw_joint],
                -abs(body_step) * self.head_recentering_gain,
                abs(body_step) * self.head_recentering_gain,
            )

        out[self.roll_joint] += clamp(
            self.roll_neutral - out[self.roll_joint],
            -self.max_roll_step,
            self.max_roll_step,
        )

        for index, limits in enumerate(self.joint_limits[: len(out)]):
            if len(limits) == 2:
                out[index] = clamp(out[index], float(limits[0]), float(limits[1]))
        return out
