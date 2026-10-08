from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

import numpy as np

from .filters import clamp


@dataclass(frozen=True)
class ImageAxis:
    joint_index: int
    px_per_deg: tuple[float, float]
    max_step_deg: float
    max_excursion_deg: float | None
    min_deg: float | None
    max_deg: float | None
    weight: float
    name: str


@dataclass
class ImageJacobianCommand:
    ok: bool
    joints_deg: list[float]
    error_px: tuple[float, float] = (0.0, 0.0)
    reason: str = ""
    delta_deg: list[float] | None = None
    debug: dict | None = None


class ImageJacobianServo:
    """Image-based visual servo using measured joint-to-pixel responses.

    Each enabled axis declares how a +1 degree motion changes image-center error
    in pixels. The controller solves a damped least-squares step, then clamps it
    through joint limits and a base-pose excursion envelope.
    """

    def __init__(self, config):
        self.config = config
        options = config.get("image_jacobian_servo", {})
        self.enabled = bool(options.get("enabled", False))
        self.deadzone = float(options.get("deadzone_px", 12.0))
        self.gain = float(options.get("gain", 0.45))
        self.max_step = float(options.get("max_step_deg", 1.2))
        self.damping = float(options.get("damping", 1e-3))
        self.divergence_px = float(options.get("divergence_px", 10.0))
        self.min_response_norm = float(options.get("min_response_norm_px_per_deg", 0.2))
        self.axes = self._load_axes(options)
        self._last_error = None
        self._last_delta = [0.0] * 6
        self._base_joints = None
        self.last_debug = {}

    @property
    def available(self):
        return self.enabled and bool(self.axes)

    def reset(self, joints=None):
        self._last_error = None
        self._last_delta = [0.0] * 6
        self.last_debug = {}
        if joints is not None and len(joints) == 6:
            self._base_joints = [float(value) for value in joints]

    def update(self, joints, target):
        current = [float(value) for value in joints]
        if not self.available:
            return self._command(False, current, reason="disabled")
        if not getattr(target, "found", False):
            self._last_error = None
            self._last_delta = [0.0] * 6
            return self._command(False, current, reason="target_lost")

        ex = float(target.u) - float(target.w) / 2.0
        ey = float(target.v) - float(target.h) / 2.0
        desired = np.asarray([
            0.0 if abs(ex) <= self.deadzone else -ex,
            0.0 if abs(ey) <= self.deadzone else -ey,
        ], dtype=float)
        if float(np.linalg.norm(desired)) <= 1e-9:
            self._last_error = (ex, ey)
            self._last_delta = [0.0] * 6
            out, clamp_debug = self._clamp_output(list(current))
            applied_delta = [out[index] - current[index] for index in range(6)]
            return self._command(
                True,
                out,
                (ex, ey),
                "deadzone",
                applied_delta,
                {"output_clamps": clamp_debug},
            )

        matrix = np.asarray(
            [
                [axis.px_per_deg[0] * axis.weight, axis.px_per_deg[1] * axis.weight]
                for axis in self.axes
            ],
            dtype=float,
        ).T
        jt = matrix.T
        lhs = jt @ matrix + self.damping * np.eye(matrix.shape[1])
        rhs = jt @ desired
        try:
            raw_delta = self.gain * np.linalg.solve(lhs, rhs)
        except np.linalg.LinAlgError:
            raw_delta = self.gain * np.linalg.pinv(matrix) @ desired

        delta = [0.0] * 6
        clipped_axes = []
        for value, axis in zip(raw_delta, self.axes):
            joint_delta = float(value) * axis.weight
            limited = clamp(joint_delta, -axis.max_step_deg, axis.max_step_deg)
            if abs(limited - joint_delta) > 1e-6:
                clipped_axes.append(axis.name)
            delta[axis.joint_index] = limited

        reason = "image_jacobian"
        if self._last_error is not None:
            previous_norm = math.hypot(*self._last_error)
            current_norm = math.hypot(ex, ey)
            if current_norm > previous_norm + self.divergence_px:
                delta = [0.0] * 6
                reason = "divergence_hold"

        self._last_error = (ex, ey)
        out = list(current)
        for index, value in enumerate(delta):
            out[index] += value
        out, clamp_debug = self._clamp_output(out)
        applied_delta = [out[index] - current[index] for index in range(6)]
        self._last_delta = applied_delta
        debug = {
            "active_axes": [axis.name for axis in self.axes],
            "desired_px": desired.tolist(),
            "raw_delta_deg": [float(value) for value in raw_delta],
            "clipped_axes": clipped_axes,
            "output_clamps": clamp_debug,
        }
        return self._command(True, out, (ex, ey), reason, applied_delta, debug)

    def _load_axes(self, options):
        axes = []
        for item in self._configured_axis_items(options):
            axis = self._parse_axis(item, options)
            if axis is not None:
                axes.append(axis)
        return axes

    def _configured_axis_items(self, options):
        items = list(options.get("axes", []) or [])
        calibration_path = options.get("calibration_path")
        if not calibration_path:
            return items
        path = Path(str(calibration_path))
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            return items
        except json.JSONDecodeError:
            return items
        summary = data.get("summary", {}) if isinstance(data, dict) else {}
        calibrated = []
        for key, value in summary.items():
            if not str(key).upper().startswith("J"):
                continue
            try:
                joint_index = int(str(key)[1:]) - 1
                response = value["avg_px_per_deg"]
            except Exception:
                continue
            base = next((item for item in items if int(item.get("joint_index", -1)) == joint_index), {})
            merged = dict(base)
            merged.update({"joint_index": joint_index, "px_per_deg": response, "enabled": base.get("enabled", True)})
            calibrated.append(merged)
        return calibrated or items

    def _parse_axis(self, item, options):
        if item.get("enabled", True) is False:
            return None
        try:
            joint_index = int(item.get("joint_index"))
            response = tuple(float(value) for value in item.get("px_per_deg", []))
        except Exception:
            return None
        if not (0 <= joint_index < 6) or len(response) != 2 or not all(math.isfinite(v) for v in response):
            return None
        if math.hypot(response[0], response[1]) < self.min_response_norm:
            return None
        limits = self._joint_limit(joint_index)
        item_min = self._maybe_float(item.get("min_deg"))
        item_max = self._maybe_float(item.get("max_deg"))
        if item_min is not None:
            limits = (max(limits[0], item_min) if limits[0] is not None else item_min, limits[1])
        if item_max is not None:
            limits = (limits[0], min(limits[1], item_max) if limits[1] is not None else item_max)
        return ImageAxis(
            joint_index=joint_index,
            px_per_deg=(response[0], response[1]),
            max_step_deg=float(item.get("max_step_deg", self.max_step)),
            max_excursion_deg=self._maybe_float(item.get("max_excursion_deg", options.get("max_excursion_deg"))),
            min_deg=limits[0],
            max_deg=limits[1],
            weight=float(item.get("weight", 1.0)),
            name=str(item.get("name") or f"J{joint_index + 1}"),
        )

    def _joint_limit(self, joint_index):
        limits = self.config.get("robot", {}).get("joint_limits_deg") or []
        if joint_index >= len(limits):
            return (None, None)
        try:
            return (float(limits[joint_index][0]), float(limits[joint_index][1]))
        except Exception:
            return (None, None)

    def _clamp_output(self, out):
        debug = []
        for axis in self.axes:
            index = axis.joint_index
            before = out[index]
            lo = axis.min_deg
            hi = axis.max_deg
            if axis.max_excursion_deg is not None and self._base_joints is not None:
                base = self._base_joints[index]
                lo = max(lo, base - axis.max_excursion_deg) if lo is not None else base - axis.max_excursion_deg
                hi = min(hi, base + axis.max_excursion_deg) if hi is not None else base + axis.max_excursion_deg
            if lo is not None:
                out[index] = max(lo, out[index])
            if hi is not None:
                out[index] = min(hi, out[index])
            if abs(out[index] - before) > 1e-6:
                debug.append({"axis": axis.name, "before": before, "after": out[index]})
        return out, debug

    def _command(self, ok, joints, error_px=(0.0, 0.0), reason="", delta=None, debug=None):
        self.last_debug = debug or {}
        return ImageJacobianCommand(ok, joints, error_px, reason, delta, debug)

    @staticmethod
    def _maybe_float(value):
        if value is None:
            return None
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if math.isfinite(out) else None
