from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from .contracts import VisionObservation


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    reason_code: str
    improvement_px: float


class MoveVerifier:
    def __init__(self, min_improvement_px: float = 1.0):
        self.min_improvement_px = float(min_improvement_px)

    def verify(self, before: VisionObservation, after: VisionObservation, target_px):
        if before.identity_id != after.identity_id:
            return VerificationResult(False, "IDENTITY_CHANGED", 0.0)
        if after.captured_at <= before.captured_at or after.frame_id == before.frame_id:
            return VerificationResult(False, "STALE_VERIFICATION", 0.0)
        tx, ty = target_px
        old = hypot(before.center_px[0] - tx, before.center_px[1] - ty)
        new = hypot(after.center_px[0] - tx, after.center_px[1] - ty)
        improvement = old - new
        return VerificationResult(improvement >= self.min_improvement_px, "VERIFIED" if improvement >= self.min_improvement_px else "NO_PROGRESS", improvement)
