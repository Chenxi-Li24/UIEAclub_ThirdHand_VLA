"""Face-first control with an observed, bound person's calibrated head anchor.

Track IDs are temporal associations, not biometric identities. Only observed
boxes can generate control points; overlap ambiguity never drives the robot.
"""
import math

from .face_lock_tracker import FaceLockTracker
from .filters import OneEuro
from .tracker import Target
from .person_lock_tracker import Candidate


def overlap(a, b):
    area = max(0., min(a.x+a.w, b.x+b.w)-max(a.x, b.x)) * max(
        0., min(a.y+a.h, b.y+b.h)-max(a.y, b.y))
    return area / max(1., a.w*a.h + b.w*b.h - area)


class FaceBodyBindings:
    """Short face-dropout tolerance with continuous observed body evidence."""
    def __init__(self, ttl_s=.8, min_score=.8, overlap_threshold=.35):
        self.ttl_s = max(0., min(2., float(ttl_s)))
        self.min_score = min_score
        self.overlap_threshold = overlap_threshold
        self.records = {}
        self.last_at = float('-inf')

    def observe(self, faces, bodies, *, now):
        if now < self.last_at:
            return
        self.last_at = now
        observed = {b.track_id for b in bodies}
        self.records = {k: v for k, v in self.records.items() if k in observed}
        for body in bodies:
            previous = self.records.get(body.track_id)
            matched = [f for f in faces if f.score >= self.min_score
                       and all(math.isfinite(v) for v in (f.u, f.v, f.w, f.h, f.score))
                       and FacePersonSelector.belongs(f, body)]
            ambiguous = (sum(b.track_id == body.track_id for b in bodies) != 1
                         or any(b.track_id != body.track_id and overlap(body, b) > self.overlap_threshold for b in bodies)
                         or len(matched) > 1
                         or any(sum(FacePersonSelector.belongs(f, b) for b in bodies) != 1 for f in matched))
            if ambiguous or previous is not None and overlap(previous[1], body) < .5:
                self.records.pop(body.track_id, None)
                continue
            if matched:
                self.records[body.track_id] = (matched[0], body, now)
            elif previous and 0 <= now-previous[2] <= self.ttl_s:
                face, old, stamp = previous
                remapped = Candidate(body.x+(face.u-old.x)*body.w/old.w,
                                     body.y+(face.v-old.y)*body.h/old.h,
                                     face.w*body.w/old.w, face.h*body.h/old.h, face.score, 'bound_face')
                self.records[body.track_id] = (remapped, body, stamp)
            else:
                self.records.pop(body.track_id, None)

    def get(self, body, bodies, *, now, not_after=None):
        record = self.records.get(body.track_id)
        if record is None or not 0 <= now-record[2] <= self.ttl_s or overlap(record[1], body) < .5:
            return None
        if not_after is not None and record[2] > not_after:
            return None
        if (sum(b.track_id == body.track_id for b in bodies) != 1
                or any(b.track_id != body.track_id and overlap(body, b) > self.overlap_threshold for b in bodies)):
            return None
        face, old, _stamp = record
        return Candidate(body.x+(face.u-old.x)*body.w/old.w, body.y+(face.v-old.y)*body.h/old.h,
                         face.w*body.w/old.w, face.h*body.h/old.h, face.score, 'bound_face')


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
        self.bindings = FaceBodyBindings(config.get('ok_switch', {}).get('face_binding_ttl_s', .8),
                                         self.face_lock.min_score, self.overlap_threshold)
        self.selection_event = None
        self._ever_selected = False
        self._last_selected_id = None
        self._body_continuous = False

    def observe_bindings(self, faces, bodies, *, now):
        self.bindings.observe(faces, bodies, now=now)

    def invalidate_body_binding(self):
        self._body_continuous = False
        self.bindings.records.clear()

    def _selection_event(self, kind, previous, now):
        self.selection_event = {'type': kind, 'from_person_id': previous, 'to_person_id': self.track_id,
                                'generation': self.generation, 'received_at': now}
        self._ever_selected = True
        self._last_selected_id = self.track_id

    @staticmethod
    def belongs(face, body):
        return (body.x <= face.u <= body.x+body.w and body.y <= face.v <= body.y+body.h*.5
                and face.w <= body.w and face.h <= body.h*.55)

    def switch_to_person(self, identity, faces, bodies, *, now):
        matches = [b for b in bodies if b.track_id == identity]
        if len(matches) != 1:
            return False
        body = matches[0]
        self.observe_bindings(faces, bodies, now=now)
        associated = [f for f in faces if self.belongs(f, body)
                      and f.score >= self.face_lock.min_score
                      and all(math.isfinite(v) for v in (f.u, f.v, f.w, f.h, f.score))]
        if not associated:
            bound = self.bindings.get(body, bodies, now=now)
            associated = [bound] if bound is not None else []
        if (len(associated) != 1 or sum(self.belongs(associated[0], b) for b in bodies) != 1
                or any(b.track_id != identity and overlap(body, b) > self.overlap_threshold for b in bodies)):
            return False
        if identity == self.track_id:
            return True
        previous = self.track_id
        self.track_id = identity
        self.generation += 1
        self._selection_event('ok', previous, now)
        self._calibrate(associated[0], body)
        self.previous_face = associated[0]
        self.last_seen = now
        # Keep only the previous display point for the normal source crossfade.
        self.source = None
        self.fx.reset()
        self.fy.reset()
        return True

    def update(self, faces, bodies, *, now, frame_size, selection_allowed=True):
        width, height = frame_size
        if not selection_allowed:
            self.invalidate_body_binding()
            return self._lost(width, height, now, 'keyword_busy')
        self.observe_bindings(faces, bodies, now=now)
        if self.last_seen is not None and now-self.last_seen > self.loss_timeout_s:
            self.track_id = self.anchor = self.previous_body = self.previous_face = None
            self.last_seen = self.last_point = self.source = None
            self._body_continuous = False
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
                           "auto_reacquire": True, 'selection_event': self.selection_event}
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
            if self.selection_event is None or self.selection_event['generation'] != self.generation:
                self._selection_event('auto_reacquire' if self._ever_selected else 'auto_initial',
                                      self._last_selected_id, now)
                self.last_debug['selection_event'] = self.selection_event
            return self._accept(face.u, face.v, face.score, "FACE", face, now, width, height)

        selected = [b for b in bodies if b.track_id == self.track_id]
        if len(selected) != 1:
            self._body_continuous = False
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
        if not self._body_continuous or self.anchor is None:
            return self._lost(width, height, now, 'identity_reconfirmation_required')
        self.previous_body = body
        u, v = body.x+self.anchor[0]*body.w, body.y+self.anchor[1]*body.h
        if not (0 <= u < width and 0 <= v < height):
            return self._lost(width, height, now, "head_anchor_outside_frame")
        self.last_debug["bbox"] = [body.x, body.y, body.w, body.h]
        return self._accept(u, v, body.score, "BODY", None, now, width, height)

    def _calibrate(self, face, body):
        self.anchor = ((face.u-body.x)/body.w, (face.v-body.y)/body.h)
        self.previous_body = body
        self._body_continuous = True

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
        self._body_continuous = False
        self.last_debug.update(lock_state="LOST", control_source="LOST", rejected=reason,
                               person_track_id=self.track_id)
        return Target(False, w=width, h=height, kind="face_person_lost", ts=now)
