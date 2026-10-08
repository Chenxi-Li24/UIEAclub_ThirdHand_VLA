from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LocalVisualJacobian:
    matrix: np.ndarray
    calibration_hash: str
    condition_number: float

    @classmethod
    def fit(cls, joint_deltas, pixel_deltas, calibration_hash: str, max_condition: float = 1e4):
        dq = np.asarray(joint_deltas, dtype=float)
        de = np.asarray(pixel_deltas, dtype=float)
        if dq.ndim != 2 or de.ndim != 2 or dq.shape[0] != de.shape[0]:
            raise ValueError("calibration samples must be aligned matrices")
        matrix = np.linalg.lstsq(dq, de, rcond=None)[0].T
        condition = float(np.linalg.cond(matrix))
        if not np.isfinite(condition) or condition > max_condition:
            raise ValueError("visual Jacobian is ill-conditioned")
        return cls(matrix=matrix, calibration_hash=calibration_hash, condition_number=condition)

    def damped_pinv(self, damping: float = 0.1):
        j = self.matrix
        return j.T @ np.linalg.inv(j @ j.T + (damping ** 2) * np.eye(j.shape[0]))
