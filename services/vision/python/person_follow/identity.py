from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from .reid import cosine_similarity


class IdentityState(str, Enum):
    UNBOUND = "UNBOUND"
    ACQUIRING = "ACQUIRING"
    LOCKED = "LOCKED"
    AMBIGUOUS = "AMBIGUOUS"
    LOST = "LOST"
    REACQUIRING = "REACQUIRING"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class IdentityResult:
    state: IdentityState
    identity_id: str | None
    track_id: int | None


class IdentityManager:
    def __init__(self, reid_threshold=0.8, ambiguity_margin=0.03):
        self.reid_threshold = float(reid_threshold)
        self.ambiguity_margin = float(ambiguity_margin)
        self.identity_id = None
        self.reference = None

    def update(self, tracks, embeddings):
        if not tracks:
            return IdentityResult(IdentityState.LOST, self.identity_id, None)
        if self.reference is None:
            winner = max(tracks, key=lambda track: track.score)
            self.reference = embeddings[winner.track_id]
            self.identity_id = str(uuid.uuid4())
            return IdentityResult(IdentityState.LOCKED, self.identity_id, winner.track_id)
        scored = sorted(((cosine_similarity(self.reference, embeddings[t.track_id]), t) for t in tracks), key=lambda item: item[0], reverse=True)
        if scored[0][0] < self.reid_threshold:
            return IdentityResult(IdentityState.LOST, self.identity_id, None)
        if len(scored) > 1 and scored[0][0] - scored[1][0] <= self.ambiguity_margin:
            return IdentityResult(IdentityState.AMBIGUOUS, self.identity_id, None)
        winner = scored[0][1]
        self.reference = embeddings[winner.track_id]
        return IdentityResult(IdentityState.LOCKED, self.identity_id, winner.track_id)
