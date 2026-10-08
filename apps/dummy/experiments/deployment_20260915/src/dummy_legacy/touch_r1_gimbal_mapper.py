from __future__ import annotations

from dataclasses import dataclass

from .filters import clamp


@dataclass
class VirtualGimbalState:
    pan_delta_deg: float = 0.0
    tilt_delta_deg: float = 0.0
    roll_delta_deg: float = 0.0


class TouchR1GimbalMapper:
    """Map DUM-E virtual pan/tilt/roll commands onto Touch R1 joints."""

    def __init__(self, config):
        options = config.get("touch_r1_gimbal", {})
        self.pan_joint = int(options.get("pan_joint_index", 0))
        self.tilt_joint = int(options.get("tilt_joint_index", 3))
        self.roll_joint = int(options.get("roll_joint_index", 5))
        self.body_yaw_joint = int(options.get("body_yaw_joint_index", 0))
        self.pan_sign = float(options.get("pan_sign", 1.0))
        self.tilt_sign = float(options.get("tilt_sign", 1.0))
        self.roll_sign = float(options.get("roll_sign", 1.0))
        self.body_yaw_sign = float(options.get("body_yaw_sign", 1.0))
        self.pan_comfort = float(options.get("pan_comfort_deg", 8.0))
        self.body_follow_gain = float(options.get("body_follow_gain", 0.25))
        self.max_body_step = float(options.get("max_body_step_deg", 0.18))
        self.roll_neutral = float(options.get("roll_neutral_deg", 0.0))
        self.max_roll_step = float(options.get("max_roll_step_deg", 0.12))
        self.joint_limits = config.get("robot", {}).get(
            "joint_limits_deg",
            [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
        )
        self.base = None

    def reset(self, joints):
        self.base = [float(value) for value in joints]

    def apply(self, joints, command: VirtualGimbalState):
        if self.base is None:
            self.reset(joints)
        out = [float(value) for value in joints]

        out[self.pan_joint] += self.pan_sign * float(command.pan_delta_deg)
        out[self.tilt_joint] += self.tilt_sign * float(command.tilt_delta_deg)

        pan_offset = out[self.pan_joint] - self.base[self.pan_joint]
        if abs(pan_offset) > self.pan_comfort:
            body_step = clamp(
                abs(pan_offset) * self.body_follow_gain,
                0.0,
                self.max_body_step,
            )
            body_step *= 1.0 if pan_offset > 0 else -1.0
            out[self.body_yaw_joint] += self.body_yaw_sign * body_step
            out[self.pan_joint] -= body_step

        out[self.roll_joint] += self.roll_sign * float(command.roll_delta_deg)
        out[self.roll_joint] += clamp(
            self.roll_neutral - out[self.roll_joint],
            -self.max_roll_step,
            self.max_roll_step,
        )

        for index, limits in enumerate(self.joint_limits[: len(out)]):
            if len(limits) == 2:
                out[index] = clamp(out[index], float(limits[0]), float(limits[1]))
        return out
