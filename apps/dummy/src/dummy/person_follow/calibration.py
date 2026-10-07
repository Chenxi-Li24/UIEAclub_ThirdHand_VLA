from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .jacobian import LocalVisualJacobian


@dataclass(frozen=True)
class CalibrationReport:
    schema_version: str
    calibration_hash: str
    camera_calibration_hash: str
    model_sha256: str
    joint_names: tuple[str, ...]
    jacobian: tuple[tuple[float, ...], ...]
    max_step_deg: tuple[float, ...]
    operating_min_deg: tuple[float, ...]
    operating_max_deg: tuple[float, ...]

    @classmethod
    def from_dict(cls, value):
        fields = dict(value)
        for name in ("joint_names", "max_step_deg", "operating_min_deg", "operating_max_deg"):
            fields[name] = tuple(fields[name])
        fields["jacobian"] = tuple(tuple(row) for row in fields["jacobian"])
        return cls(**fields)

    def validate(self, camera_hash, model_hash, joints):
        if camera_hash != self.camera_calibration_hash or model_hash != self.model_sha256:
            raise ValueError("calibration provenance mismatch")
        if len(joints) != len(self.joint_names):
            raise ValueError("joint count mismatch")
        if any(not low <= float(value) <= high for value, low, high in zip(joints, self.operating_min_deg, self.operating_max_deg)):
            raise ValueError("outside calibrated operating range")

    def model(self):
        matrix = np.asarray(self.jacobian, dtype=float)
        return LocalVisualJacobian(matrix, self.calibration_hash, float(np.linalg.cond(matrix)))
