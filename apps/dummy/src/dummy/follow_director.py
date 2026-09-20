from __future__ import annotations

from .filters import clamp


class FollowDirector:
    def __init__(self, config):
        f = config.get("follow", {})
        self.pan_joint = int(f.get("pan_joint_index", 0))
        self.tilt_joint = int(f.get("tilt_joint_index", 3))
        self.roll_joint = int(f.get("roll_joint_index", 4))
        self.k_pan = float(f.get("k_pan_deg_per_px", 0.018))
        self.k_tilt = float(f.get("k_tilt_deg_per_px", 0.015))
        self.k_roll = float(f.get("k_roll_deg_per_px", 0.010))
        self.sign_pan = float(f.get("sign_pan", -1))
        self.sign_tilt = float(f.get("sign_tilt", 1))
        self.sign_roll = float(f.get("sign_roll", -1))
        self.deadzone = float(f.get("deadzone_px", 30))
        self.max_corr = float(f.get("max_correction_deg", 10))
        self.max_pan_corr = float(f.get("max_pan_correction_deg", self.max_corr))
        self.max_tilt_corr = float(f.get("max_tilt_correction_deg", self.max_corr))
        self.max_roll = float(f.get("max_roll_deg", 4.0))
        self.step = float(f.get("max_step_deg", 0.35))
        self.roll_step = float(f.get("max_roll_step_deg", min(self.step, 1.0)))
        self.search_max = float(f.get("search_max_deg", min(self.max_corr, 4.0)))
        self.search_tilt_max = float(f.get("search_tilt_max_deg", min(self.search_max, 2.0)))
        self.joint_limits = config.get("robot", {}).get("joint_limits_deg", [])
        self.base = None
        self.current = None
        self.last_error_px = (0.0, 0.0)
        self.last_desired = None

    def reset_base(self, joints):
        self.base = list(joints)
        self.current = list(joints)
        self.last_error_px = (0.0, 0.0)
        self.last_desired = list(joints)

    def target_for(self, joints, target):
        if self.base is None:
            self.reset_base(joints)
        out = list(joints)
        if not target.found:
            return out
        if str(target.kind).endswith("_hold"):
            # A held target is memory, not a fresh observation.  Preserve the
            # current gaze pose instead of integrating stale pixel error.
            self.last_error_px = (
                target.u - target.w / 2,
                target.v - target.h / 2,
            )
            self.last_desired = list(out)
            return out
        ex = target.u - target.w / 2
        ey = target.v - target.h / 2
        self.last_error_px = (ex, ey)

        # Pan and tilt are visual-servo axes.  A persistent image error must
        # keep advancing them; anchoring them to the startup pose makes the
        # arm stop after one correction even while the target is off-centre.
        if abs(ex) > self.deadzone:
            out[self.pan_joint] += clamp(
                self.sign_pan * self.k_pan * ex,
                -min(self.step, self.max_pan_corr),
                min(self.step, self.max_pan_corr),
            )
        if abs(ey) > self.deadzone:
            out[self.tilt_joint] += clamp(
                self.sign_tilt * self.k_tilt * ey,
                -min(self.step, self.max_tilt_corr),
                min(self.step, self.max_tilt_corr),
            )

        # A wrong camera-axis sign must not be able to drive the arm all the
        # way to a hardware joint limit.  Follow remains bounded around the
        # pose captured when this lock began.
        for index, excursion in (
            (self.pan_joint, self.max_pan_corr),
            (self.tilt_joint, self.max_tilt_corr),
        ):
            out[index] = clamp(
                out[index],
                self.base[index] - excursion,
                self.base[index] + excursion,
            )

        # Roll is expressive rather than a centring axis, so keep it bounded
        # around the pose captured at the start of following.
        desired_roll = self.base[self.roll_joint]
        if abs(ex) > self.deadzone:
            desired_roll += clamp(
                self.sign_roll * self.k_roll * ex,
                -self.max_roll,
                self.max_roll,
            )
        out[self.roll_joint] += clamp(
            desired_roll - out[self.roll_joint],
            -self.roll_step,
            self.roll_step,
        )
        for index, limits in enumerate(self.joint_limits[: len(out)]):
            if len(limits) == 2:
                out[index] = clamp(out[index], float(limits[0]), float(limits[1]))
        self.last_desired = list(out)
        self.current = out
        return out

    def search_offset(self, phase):
        import math
        return math.sin(phase) * self.search_max

    def search_target(self, joints, phase, *, scale=1.0):
        import math

        if self.base is None:
            self.reset_base(joints)
        out = list(joints)
        desired = list(self.base)
        desired[self.pan_joint] += self.search_offset(phase) * float(scale)
        desired[self.tilt_joint] += (
            math.sin(float(phase) * 0.5) * self.search_tilt_max * float(scale)
        )
        for i in range(6):
            out[i] += clamp(desired[i] - out[i], -self.step, self.step)
        for index, limits in enumerate(self.joint_limits[: len(out)]):
            if len(limits) == 2:
                out[index] = clamp(out[index], float(limits[0]), float(limits[1]))
        self.current = out
        self.last_desired = list(desired)
        return out
