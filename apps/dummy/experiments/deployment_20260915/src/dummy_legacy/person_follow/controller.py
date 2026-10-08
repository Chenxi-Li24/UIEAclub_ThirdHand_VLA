from __future__ import annotations

import numpy as np

from .jacobian import LocalVisualJacobian


class JacobianController:
    def __init__(self, model: LocalVisualJacobian, gain=0.5, max_step_deg=(0.5, 0.5), deadband_px=2.0, damping=0.1):
        self.model = model
        self.gain = float(gain)
        self.max_step = np.asarray(max_step_deg, dtype=float)
        self.deadband_px = float(deadband_px)
        self.damping = float(damping)

    def compute(self, error_px):
        error = np.asarray(error_px, dtype=float)
        if not np.all(np.isfinite(error)):
            raise ValueError("pixel error must be finite")
        if np.linalg.norm(error) <= self.deadband_px:
            return tuple(0.0 for _ in range(self.model.matrix.shape[1]))
        step = -self.gain * self.model.damped_pinv(self.damping) @ error
        step = np.clip(step, -self.max_step, self.max_step)
        return tuple(float(v) for v in step)
