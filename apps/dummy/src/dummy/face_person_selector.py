"""Face-first control with an observed, bound person's calibrated head anchor.

Track IDs are temporal associations, not biometric identities. Only observed
boxes can generate control points; overlap ambiguity never drives the robot.
"""
import math

from .face_lock_tracker import FaceLockTracker
from .filters import OneEuro
from .tracker import Target


def overlap(a, b):
    area = max(0., min(a.x+a.w, b.x+b.w)-max(a.x, b.x)) * max(
        0., min(a.y+a.h, b.y+b.h)-max(a.y, b.y))
    return area / max(1., a.w*a.h + b.w*b.h - area)


class FacePersonSelector:
    def __init__(self, config):
        self.config = config
        options = config.get("person_tracking", {})
        self.loss_timeout_s = float(options.get("loss_timeout_s", 1.0))
        self.blend_s = max(.01, float(options.get("source_blend_s", .3)))
        self.overlap_threshold = float(options.get("overlap_pause_iou", .35))
        self.face_lock = FaceLockTracker(config)
        hz = float(config.get("vision", {}).get("hz", 15))
        self.fx = OneEuro(hz, .7, .08)
        self.fy = OneEuro(hz, .7, .08)
        self.track_id = None
        self.anchor = None
        self.previous_body = None
        self.previous_face = None
        self.last_seen = None
        self.last_point = None
        self.source = None
        self.switch_at = 0.
        self.offset = (0., 0.)
        self.generation = 0
        self.last_debug = {}

    @staticmethod
    def belongs(face, body):
        return (body.x <= face.u <= body.x+body.w and body.y <= face.v <= body.y+body.h*.5
                and face.w <= body.w and face.h <= body.h*.55)

    def update(self, faces, bodies, *, now, frame_size):
        width, height = frame_size
        if self.last_seen is not None and now-self.last_seen > self.loss_timeout_s:
            self.track_id = self.anchor = self.previous_body = self.previous_face = None
            self.last_seen = self.last_point = self.source = None
            self.face_lock = FaceLockTracker(self.config)
            self.fx.reset()
            self.fy.reset()
        faces = [f for f in faces if f.score >= self.face_lock.min_score and f.w > 0 and f.h > 0
                 and all(math.isfinite(v) for v in (f.u, f.v, f.w, f.h, f.score))]
        bodies = [b for b in bodies if b.w > 0 and b.h > 0
                  and all(math.isfinite(v) for v in (b.x, b.y, b.w, b.h, b.score))]
        self.last_debug = {"follow_target": "face_person", "face_count": len(faces),
                           "face_boxes": [[f.u-f.w/2, f.v-f.h/2, f.w, f.h] for f in faces],
                           "face_scores": [f.score for f in faces],
                           "person_tracks": [{"track_id": b.track_id, "bbox": [b.x, b.y, b.w, b.h],
                                              "score": b.score} for b in bodies],
                           "person_track_id": self.track_id, "selection_generation": self.generation,
                           "auto_reacquire": True}
        if self.track_id is None:
            chosen = self.face_lock.update(faces, now=now, frame_size=frame_size)
            if not chosen.found or "hold" in chosen.kind:
                return self._lost(width, height, now, self.face_lock.state)
            face = self.face_lock.previous
            matches = [b for b in bodies if self.belongs(face, b)]
            if len(matches) > 1:
                return self._lost(width, height, now, "face_body_ambiguous")
            if self.previous_face is None or self.face_lock.selection_generation != getattr(self, "face_generation", None):
                self.generation += 1
                self.face_generation = self.face_lock.selection_generation
                self.fx.reset()
                self.fy.reset()
                self.last_point = self.source = None
            if matches:
                self.track_id = matches[0].track_id
                self._calibrate(face, matches[0])
            return self._accept(face.u, face.v, face.score, "FACE", face, now, width, height)

        selected = [b for b in bodies if b.track_id == self.track_id]
        if len(selected) != 1:
            # Face-only continuation is spatial and short-range, not a new ID bind.
            previous = self.previous_face
            nearby = [f for f in faces if previous is not None
                      and math.hypot(f.u-previous.u, f.v-previous.v) < max(40., previous.w*1.5)
                      and .35 <= f.w*f.h/(previous.w*previous.h) <= 2.8
                      and not any(self.belongs(f, b) for b in bodies)]
            if len(nearby) == 1:
                f = nearby[0]
                return self._accept(f.u, f.v, f.score, "FACE", f, now, width, height)
            return self._lost(width, height, now, "selected_person_missing")
        body = selected[0]
        if any(b.track_id != self.track_id and overlap(body, b) > self.overlap_threshold for b in bodies):
            return self._lost(width, height, now, "people_overlap_ambiguous")
        previous = self.previous_body
        if previous and (math.hypot(body.x+body.w/2-previous.x-previous.w/2,
                                   body.y+body.h/2-previous.y-previous.h/2) > max(120., previous.w)
                         or not .3 <= body.w*body.h/(previous.w*previous.h) <= 3.):
            return self._lost(width, height, now, "track_discontinuity")
        associated = [f for f in faces if self.belongs(f, body)]
        if len(associated) > 1 or any(sum(self.belongs(f, b) for b in bodies) != 1 for f in associated):
            return self._lost(width, height, now, "face_body_ambiguous")
        if associated:
            f = associated[0]
            self._calibrate(f, body)
            return self._accept(f.u, f.v, f.score, "FACE", f, now, width, height)
        self.previous_body = body
        u, v = body.x+self.anchor[0]*body.w, body.y+self.anchor[1]*body.h
        if not (0 <= u < width and 0 <= v < height):
            return self._lost(width, height, now, "head_anchor_outside_frame")
        self.last_debug["bbox"] = [body.x, body.y, body.w, body.h]
        return self._accept(u, v, body.score, "BODY", None, now, width, height)

    def _calibrate(self, face, body):
        self.anchor = ((face.u-body.x)/body.w, (face.v-body.y)/body.h)
        self.previous_body = body

    def _accept(self, u, v, score, source, face, now, width, height):
        if source != self.source:
            self.offset = (self.last_point[0]-u, self.last_point[1]-v) if self.last_point else (0., 0.)
            self.switch_at = now
        blend = max(0., 1.-(now-self.switch_at)/self.blend_s)
        u, v = self.fx(u+self.offset[0]*blend), self.fy(v+self.offset[1]*blend)
        self.last_point = (u, v)
        self.last_seen = now
        self.source = source
        if face is not None:
            self.previous_face = face
            self.last_debug["bbox"] = [face.u-face.w/2, face.v-face.h/2, face.w, face.h]
        self.last_debug.update(lock_state=source, control_source=source, person_track_id=self.track_id,
                               selection_generation=self.generation, head_anchor=self.anchor)
        return Target(True, u, v, width, height, score, "face_person_"+source.lower(), now)

    def _lost(self, width, height, now, reason):
        self.last_debug.update(lock_state="LOST", control_source="LOST", rejected=reason,
                               person_track_id=self.track_id)
        return Target(False, w=width, h=height, kind="face_person_lost", ts=now)
