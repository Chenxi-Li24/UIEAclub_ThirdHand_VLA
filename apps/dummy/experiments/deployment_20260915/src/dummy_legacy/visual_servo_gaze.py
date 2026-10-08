from __future__ import annotations

from dataclasses import dataclass

from .filters import clamp


@dataclass
class VirtualGimbalCommand:
    found: bool
    pan_delta_deg: float = 0.0
    tilt_delta_deg: float = 0.0
    roll_delta_deg: float = 0.0
    hold: bool = False
    error_px: tuple[float, float] = (0.0, 0.0)


class VisualServoGazeController:
    """Image-based visual servo controller for DUM-E gaze following."""

    def __init__(self, config):
        options = config.get("visual_servo_gaze", {})
        self.deadzone = float(options.get("deadzone_px", 12))
        self.pan_kp = float(options.get("pan_kp_deg_per_px", -0.02))
        self.tilt_kp = float(options.get("tilt_kp_deg_per_px", -0.02))
        self.max_pan_step = float(options.get("max_pan_step_deg", 0.75))
        self.max_tilt_step = float(options.get("max_tilt_step_deg", 0.75))
        self.tilt_enabled = bool(options.get("tilt_enabled", True))
        self.lost_hold_frames = int(options.get("lost_hold_frames", 3))
        self.divergence_px = float(options.get("divergence_px", 8.0))
        self._last_command = VirtualGimbalCommand(False)
        self._lost_frames = 0

    def reset(self):
        self._last_command = VirtualGimbalCommand(False)
        self._lost_frames = 0

    def update(self, target):
        if not getattr(target, "found", False):
            self._lost_frames += 1
            if self._last_command.found and self._lost_frames <= self.lost_hold_frames:
                return VirtualGimbalCommand(
                    True,
                    self._last_command.pan_delta_deg,
                    self._last_command.tilt_delta_deg,
                    self._last_command.roll_delta_deg,
                    True,
                    self._last_command.error_px,
                )
            return VirtualGimbalCommand(False)

        self._lost_frames = 0
        ex = float(target.u) - float(target.w) / 2.0
        ey = float(target.v) - float(target.h) / 2.0
        pan = 0.0
        tilt = 0.0
        if abs(ex) > self.deadzone:
            pan = clamp(self.pan_kp * ex, -self.max_pan_step, self.max_pan_step)
        if self.tilt_enabled and abs(ey) > self.deadzone:
            tilt = clamp(self.tilt_kp * ey, -self.max_tilt_step, self.max_tilt_step)
        if self._axis_worsened(ex, self._last_command.error_px[0], self._last_command.pan_delta_deg):
            pan = 0.0
        if self._axis_worsened(ey, self._last_command.error_px[1], self._last_command.tilt_delta_deg):
            tilt = 0.0
        self._last_command = VirtualGimbalCommand(True, pan, tilt, 0.0, False, (ex, ey))
        return self._last_command

    def _axis_worsened(self, error, previous_error, previous_delta):
        if not self._last_command.found or abs(previous_delta) <= 1e-9:
            return False
        return abs(error) > abs(previous_error) + self.divergence_px
