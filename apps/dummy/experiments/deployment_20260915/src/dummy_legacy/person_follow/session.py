from __future__ import annotations

from enum import Enum

from .contracts import VisionObservation


class FollowState(str, Enum):
    IDLE = "IDLE"
    ACQUIRING = "ACQUIRING"
    LOCKED = "LOCKED"
    HOLDING = "HOLDING"
    MOVING = "MOVING"
    VERIFYING = "VERIFYING"
    LOST = "LOST"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAULT = "FAULT"


class FollowSession:
    def __init__(self, session_id: str, max_observation_age_s: float = 0.5):
        self.session_id = session_id
        self.max_observation_age_s = max_observation_age_s
        self.state = FollowState.ACQUIRING
        self.identity_id: str | None = None

    @property
    def can_propose(self) -> bool:
        return self.state == FollowState.LOCKED and self.identity_id is not None

    def accept(self, observation: VisionObservation, now: float) -> FollowState:
        if now - observation.captured_at > self.max_observation_age_s:
            self.state = FollowState.HOLDING
        elif observation.identity_state != "LOCKED" or not observation.identity_id:
            self.state = FollowState.HOLDING
        elif self.identity_id not in (None, observation.identity_id):
            self.state = FollowState.HOLDING
        else:
            self.identity_id = observation.identity_id
            self.state = FollowState.LOCKED
        return self.state

    def stop(self) -> FollowState:
        self.state = FollowState.STOPPED
        return self.state
