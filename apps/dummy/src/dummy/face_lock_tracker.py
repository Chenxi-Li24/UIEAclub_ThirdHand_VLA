"""Face-only spatial continuity, with configurable automatic reacquisition.

This is not biometric identity recognition. Ambiguous nearby faces are held,
not ranked again by confidence or size after the initial selection.
"""
from dataclasses import asdict
import math

from .filters import OneEuro
from .tracker import Target


class FaceLockTracker:
    def __init__(self, config):
        options = config.get("face_lock", {})
        self.loss_timeout_s = float(options.get("loss_timeout_s", 1.0))
        self.auto_reacquire = bool(options.get("auto_reacquire", True))
        self.max_distance_px = float(options.get("max_distance_px", 120.0))
        self.ambiguity_margin_px = float(options.get("ambiguity_margin_px", 30.0))
        self.confirm_frames = max(1, int(options.get("confirm_frames", 2)))
        vision = config.get("vision_service", {})
        self.min_score = float(vision.get("yunet_face_min_score", .8) if vision.get("face_detector") == "yunet"
                               else vision.get("mediapipe_face_min_score", .5))
        hz = float(config.get("vision", {}).get("hz", 15))
        self.fx = OneEuro(hz, options.get("filter_min_cutoff", 0.7), options.get("filter_beta", 0.08))
        self.fy = OneEuro(hz, options.get("filter_min_cutoff", 0.7), options.get("filter_beta", 0.08))
        self.locked = None
        self.previous = None
        self.pending = None
        self.pending_count = 0
        self.last_seen = None
        self.state = "waiting_for_first_face"
        self.ever_selected = False
        self.selection_generation = 0
        self.last_debug = {}

    def update(self, candidates, *, now, frame_size):
        width, height = frame_size
        candidates = [item for item in candidates if "face" in item.kind
                      and item.score >= self.min_score and item.w > 0 and item.h > 0
                      and all(math.isfinite(x) for x in (item.u, item.v, item.w, item.h, item.score))]
        self.last_debug = {"follow_target": "face", "face_count": len(candidates),
                           "face_boxes": [[c.u - c.w / 2, c.v - c.h / 2, c.w, c.h] for c in candidates],
                           "face_scores": [c.score for c in candidates], "auto_reacquire": self.auto_reacquire,
                           "selection_generation": self.selection_generation}
        if self.state == "waiting_for_ok":
            return self._missing(width, height, now)
        if self.last_seen is not None and now - self.last_seen > self.loss_timeout_s:
            if not self.auto_reacquire:
                self.state = "waiting_for_ok"
                return self._missing(width, height, now)
            self.locked = self.previous = self.pending = self.last_seen = None
            self.pending_count = 0
            self.state = "reacquiring_face"

        if self.locked is None:
            if not candidates:
                self.pending = None
                self.pending_count = 0
                return self._missing(width, height, now)
            best = max(candidates, key=lambda c: c.score -
                       math.hypot(c.u - width / 2, c.v - height / 2) / max(width, height))
            if self.pending is None or self._distance(best, self.pending) > self.max_distance_px:
                self.pending_count = 0
            self.pending = best
            self.pending_count += 1
            if self.pending_count < self.confirm_frames:
                self.state = "confirming_face" if self.ever_selected else "confirming_first_face"
                return self._missing(width, height, now)
            self.fx.reset()
            self.fy.reset()
            return self._accept(best, now, width, height)

        # Associate with the last raw box, not the smoothed command point.
        radius = min(self.max_distance_px, max(60., max(self.previous.w, self.previous.h) * 1.5))
        matches = [c for c in candidates if self._distance(c, self.previous) <= radius
                   and 0.35 <= c.w * c.h / (self.previous.w * self.previous.h) <= 2.8]
        matches.sort(key=lambda c: self._distance(c, self.previous))
        ambiguous = len(matches) > 1 and (
            self._distance(matches[1], self.previous) - self._distance(matches[0], self.previous)
            < self.ambiguity_margin_px
        )
        if not matches or ambiguous:
            self.state = "holding"
            self.last_debug["rejected"] = "face_association_ambiguous" if ambiguous else "selected_face_missing"
            self.last_debug["lock_state"] = self.state
            return Target(True, self.locked.u, self.locked.v, width, height,
                          self.locked.score, "face_lock_hold", self.last_seen)
        return self._accept(matches[0], now, width, height)

    @staticmethod
    def _distance(a, b):
        return math.hypot(a.u - b.u, a.v - b.v)

    def _accept(self, candidate, now, width, height):
        if self.locked is None:
            self.ever_selected = True
            self.selection_generation += 1
        self.previous = candidate
        self.last_seen = now
        self.state = "tracking"
        self.locked = Target(True, self.fx(candidate.u), self.fy(candidate.v), width, height,
                             candidate.score, "face_lock", now)
        self.last_debug.update(lock_state=self.state, lock_candidate=asdict(candidate),
                               selection_generation=self.selection_generation,
                               bbox=[candidate.u - candidate.w / 2, candidate.v - candidate.h / 2,
                                     candidate.w, candidate.h])
        return self.locked

    def _missing(self, width, height, now):
        self.last_debug["lock_state"] = self.state
        return Target(False, w=width, h=height, kind="face_" + self.state, ts=now)
