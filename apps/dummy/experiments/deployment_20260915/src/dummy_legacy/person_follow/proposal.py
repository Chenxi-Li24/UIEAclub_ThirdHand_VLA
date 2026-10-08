from __future__ import annotations

import uuid

from .contracts import MotionProposal, VisionObservation


class ProposalFactory:
    def __init__(self, max_age_s: float = 0.25):
        self.max_age_s = float(max_age_s)

    def create(self, session_id: str, observation: VisionObservation, joints_deg, now: float):
        if observation.identity_state != "LOCKED" or not observation.identity_id:
            raise ValueError("a locked identity is required")
        return MotionProposal(
            schema_version="1.0", proposal_id=str(uuid.uuid4()), session_id=session_id,
            identity_id=observation.identity_id, frame_id=observation.frame_id,
            calibration_hash=observation.calibration_hash, created_at=now,
            expires_at=now + self.max_age_s, joints_deg=tuple(joints_deg),
        )
