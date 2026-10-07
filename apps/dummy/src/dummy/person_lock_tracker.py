from __future__ import annotations

from dataclasses import dataclass

from .filters import OneEuro
from .tracker import Target


@dataclass
class Candidate:
    u: float
    v: float
    w: float
    h: float
    score: float
    kind: str


class PersonLockTracker:
    """Stable person lock inspired by action-camera subject tracking.

    Detectors are allowed to be noisy.  This layer owns target identity,
    smoothing, short occlusion hold, and deliberate relock.
    """

    def __init__(self, config):
        options = config.get("person_lock", {})
        self.hold_s = float(options.get("hold_s", 1.0))
        self.jump_px = float(options.get("jump_px", 140.0))
        self.relock_frames = int(options.get("relock_frames", 3))
        self.min_score = float(options.get("min_score", 0.15))
        self.filter_hz = float(options.get("filter_hz", 15.0))
        self.fx = OneEuro(self.filter_hz, options.get("filter_min_cutoff", 1.0), options.get("filter_beta", 0.04))
        self.fy = OneEuro(self.filter_hz, options.get("filter_min_cutoff", 1.0), options.get("filter_beta", 0.04))
        self.locked = None
        self.last_seen = 0.0
        self.pending = None
        self.pending_count = 0
        self.state = "idle"
        self.last_debug = {}

    def update(self, candidates, *, now, frame_size):
        width, height = frame_size
        candidates = [item for item in candidates if float(item.score) >= self.min_score]
        best = self._best_candidate(candidates, width, height)
        if best is None:
            return self._hold(now, width, height)

        if self.locked is None:
            return self._accept(best, now, width, height)

        distance = _distance((best.u, best.v), (self.locked.u, self.locked.v))
        if distance <= self.jump_px:
            self.pending = None
            self.pending_count = 0
            return self._accept(best, now, width, height)

        if self.pending is None or _distance((best.u, best.v), (self.pending.u, self.pending.v)) > self.jump_px:
            self.pending = best
            self.pending_count = 1
        else:
            self.pending = best
            self.pending_count += 1
        self.last_debug = {
            "candidate": best,
            "rejected": "far_candidate_waiting_for_relock",
            "pending_count": self.pending_count,
        }
        if self.pending_count >= self.relock_frames:
            self.fx.reset()
            self.fy.reset()
            self.pending = None
            self.pending_count = 0
            return self._accept(best, now, width, height)
        return self._hold(now, width, height)

    def _accept(self, candidate, now, width, height):
        target = Target(
            True,
            self.fx(float(candidate.u)),
            self.fy(float(candidate.v)),
            int(width),
            int(height),
            float(candidate.score),
            "person_lock",
            float(now),
        )
        self.locked = target
        self.last_seen = float(now)
        self.state = "tracking"
        self.last_debug = {"candidate": candidate, "state": self.state}
        return target

    def _hold(self, now, width, height):
        if self.locked is None or float(now) - self.last_seen > self.hold_s:
            self.state = "lost"
            return Target(False, w=int(width), h=int(height), kind="person_lock_lost", ts=float(now))
        self.state = "holding"
        age = max(0.0, float(now) - self.last_seen)
        return Target(
            True,
            self.locked.u,
            self.locked.v,
            int(width),
            int(height),
            max(0.01, self.locked.score * (1.0 - age / self.hold_s)),
            "person_lock_hold",
            self.last_seen,
        )

    def _best_candidate(self, candidates, width, height):
        if not candidates:
            return None
        cx, cy = float(width) / 2.0, float(height) / 2.0

        def rank(item):
            center_penalty = _distance((item.u, item.v), (cx, cy)) / max(width, height)
            size_bonus = min(1.0, (float(item.w) * float(item.h)) / max(1.0, width * height) * 8.0)
            kind_bonus = 0.15 if "face" in str(item.kind) else 0.0
            return float(item.score) + size_bonus + kind_bonus - center_penalty

        return max(candidates, key=rank)


def _distance(a, b):
    dx = float(a[0]) - float(b[0])
    dy = float(a[1]) - float(b[1])
    return (dx * dx + dy * dy) ** 0.5
