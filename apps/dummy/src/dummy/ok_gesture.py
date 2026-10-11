"""HaGRID hand observations select a person; they never own robot motion."""
from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
import threading
import time

from .config import APP_ROOT, resolve_project_path
from .face_person_selector import FacePersonSelector, FaceBodyBindings, overlap
from .person_pose import PoseOwnerMatcher

SELECTION_GESTURE = 'palm'


@dataclass(frozen=True)
class HandGesture:
    x: float
    y: float
    w: float
    h: float
    score: float
    label: str


@dataclass(frozen=True)
class GestureFrame:
    frame_id: int
    received_at: float
    epoch: int
    hands: tuple
    bodies: tuple
    faces: tuple
    inference_ms: float
    poses: tuple = ()
    pose_inference_ms: float = 0.


class HagridDetector:
    def __init__(self, options, *, model=None):
        self.confidence = float(options.get('min_confidence', .8))
        self.device = options.get('device', 'cpu')
        self.imgsz = int(options.get('imgsz', 640))
        if model is None:
            manifest = json.loads((APP_ROOT / 'configs' / 'ok-gesture-model.json').read_text())
            path = resolve_project_path(options.get('model_path', manifest['path']))
            if not path.is_file():
                raise RuntimeError('Palm gesture weights missing; run apps/dummy/apps/prepare_ok_model.py')
            with path.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            if digest != manifest['sha256']:
                raise ValueError('HaGRID model hash mismatch')
            from ultralytics import YOLO
            model = YOLO(str(path))
        self.model = model
        names = model.names
        entries = names.items() if isinstance(names, dict) else enumerate(names)
        self.gesture_ids = [int(i) for i, label in entries if label == SELECTION_GESTURE]
        if len(self.gesture_ids) != 1:
            raise ValueError('gesture model must contain exactly one palm class')

    def detect(self, frame):
        results = self.model.predict(frame, classes=self.gesture_ids, conf=self.confidence,
                                     imgsz=self.imgsz, device=self.device, verbose=False)
        hands = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            def values(value):
                return value.cpu().tolist() if hasattr(value, 'cpu') else value.tolist()
            for bbox, score, label in zip(values(boxes.xyxy), values(boxes.conf), values(boxes.cls)):
                x1, y1, x2, y2 = map(float, bbox)
                if (int(label) in self.gesture_ids and score >= self.confidence and x2 > x1 and y2 > y1
                        and all(math.isfinite(v) for v in (*bbox, score))):
                    hands.append(HandGesture(x1, y1, x2-x1, y2-y1, float(score), SELECTION_GESTURE))
        return hands


class GestureWorker:
    """One inference and one replaceable pending frame, sharing the RGB reader."""
    def __init__(self, detector, *, hz=8, pose_detector=None):
        self.detector = detector
        self.pose_detector = pose_detector
        self.period = 1 / max(1., float(hz))
        self.condition = threading.Condition()
        self.pending = self.result = None
        self.stopped = False
        self.error = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='dummy-ok', daemon=False)
        self.thread.start()

    def submit(self, frame, frame_id, received_at, epoch, bodies, faces):
        with self.condition:
            if not self.stopped:
                self.pending = (frame, frame_id, received_at, epoch, tuple(bodies), tuple(faces))
                self.condition.notify()

    def latest(self):
        with self.condition:
            return self.result

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped or self.pending is not None)
                if self.stopped:
                    return
                frame, sequence, stamp, epoch, bodies, faces = self.pending
                self.pending = None
            started = time.monotonic()
            try:
                hands = tuple(self.detector.detect(frame))
                pose_started = time.monotonic()
                poses = tuple(self.pose_detector.detect(frame)) if hands and self.pose_detector is not None else ()
                pose_ms = (time.monotonic()-pose_started)*1000 if hands and self.pose_detector is not None else 0.
            except Exception as exc:
                with self.condition:
                    self.error = str(exc)
                    self.result = None
                return
            with self.condition:
                self.result = GestureFrame(sequence, stamp, epoch, hands, bodies, faces,
                                           (time.monotonic()-started)*1000, poses, pose_ms)
                deadline = started+self.period
                while not self.stopped and time.monotonic() < deadline:
                    self.condition.wait(timeout=deadline-time.monotonic())

    def close(self):
        with self.condition:
            self.stopped = True
            self.pending = self.result = None
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=8.)
            if self.thread.is_alive():
                raise RuntimeError('Palm gesture inference did not stop; shared services were not stopped')


class OkSwitch:
    def __init__(self, options):
        self.confidence = float(options.get('min_confidence', .8))
        self.hold_s = float(options.get('hold_s', .5))
        self.release_s = float(options.get('release_s', .3))
        self.cooldown_s = float(options.get('cooldown_s', 1.))
        self.max_age_s = float(options.get('max_result_age_s', .5))
        self.max_gap_s = float(options.get('max_confirmation_gap_s', .35))
        self.confirm_frames = max(2, int(options.get('confirm_frames', 3)))
        window_frames = int(options.get('confirmation_window_frames', 0))
        self.window_frames = max(self.confirm_frames, window_frames) if window_frames > 0 else 0
        self.confirmation_results = deque(maxlen=self.window_frames or self.confirm_frames)
        self.pose_matcher = PoseOwnerMatcher(options)
        self.bindings = FaceBodyBindings(options.get('face_binding_ttl_s', .8),
                                         options.get('face_min_confidence', .8))
        self.epoch = self.sequence = None
        self.scene_epoch = None
        self.candidate = None
        self.candidate_body = None
        self.since = self.last_stamp = None
        self.count = 0
        self.latched = {}
        self.latched_bodies = {}
        self.release_barriers = {}
        self.last_frame_stamp = None
        self.cooldown_until = 0.
        self.debug = {'reason': 'waiting_for_gesture', 'progress': 0., 'trigger_label': SELECTION_GESTURE}

    def reset_confirmation(self, reason):
        self.candidate = self.since = self.last_stamp = None
        self.candidate_body = None
        self.count = 0
        self.confirmation_results.clear()
        self.debug = {'reason': reason, 'progress': 0., 'trigger_label': SELECTION_GESTURE}

    def record_confirmation(self, stamp, valid, evidence):
        if self.window_frames:
            self.confirmation_results.append((stamp, valid))
            valid_stamps = [at for at, accepted in self.confirmation_results if accepted]
            if not valid_stamps:
                self.reset_confirmation('no_ok')
                return
            self.since = valid_stamps[0]
            self.count = len(valid_stamps)
        else:
            self.count += 1
        self.last_stamp = stamp
        progress = min(1., (stamp-self.since)/max(.001, self.hold_s))
        self.debug = {'reason': 'confirming_ok' if valid else 'palm_gap_tolerated',
                      'person_track_id': self.candidate, 'progress': progress,
                      'frames': self.count, 'owner_evidence': evidence,
                      'trigger_label': SELECTION_GESTURE}
        if self.window_frames:
            self.debug['window_results'] = len(self.confirmation_results)

    def reject_uncertain(self, reason):
        self.latched = dict.fromkeys(self.latched)
        self.reset_confirmation(reason)

    def invalidate_observations(self, reason, observed_at):
        self.bindings.records.clear()
        self.release_barriers.update(dict.fromkeys(self.latched, observed_at))
        self.reject_uncertain(reason)

    def owner(self, hand, bodies, poses=()):
        return self.pose_matcher.owners(hand, poses, bodies)

    def unique_face(self, body, faces, bodies):
        matched = [f for f in faces if f.score >= self.bindings.min_score and FacePersonSelector.belongs(f, body)]
        return (len(matched) == 1
                and sum(FacePersonSelector.belongs(matched[0], b) for b in bodies) == 1)

    def has_face_evidence(self, body, faces, bodies, *, now, not_after=None):
        if (sum(b.track_id == body.track_id for b in bodies) != 1
                or any(b.track_id != body.track_id and overlap(b, body) > .35 for b in bodies)):
            return False
        matched = [f for f in faces if f.score >= self.bindings.min_score
                   and FacePersonSelector.belongs(f, body)]
        # Cached evidence tolerates absence, never an explicitly ambiguous face.
        if matched:
            return self.unique_face(body, faces, bodies)
        return self.bindings.get(body, bodies, now=now, not_after=not_after) is not None

    def update(self, result, *, now, bodies, faces, epoch, allowed=True, scene_epoch=None, observed_at=None):
        if not allowed:
            self.bindings.records.clear()
            self.reject_uncertain('keyword_busy')
            return None
        if self.epoch != epoch:
            self.epoch, self.sequence = epoch, None
            scene_epoch = epoch if scene_epoch is None else scene_epoch
            if self.scene_epoch != scene_epoch:
                self.latched.clear()
                self.latched_bodies.clear()
                self.release_barriers.clear()
                self.bindings.records.clear()
                self.bindings.last_at = float('-inf')
                self.scene_epoch = scene_epoch
            else:
                self.latched = dict.fromkeys(self.latched)
                self.bindings.records.clear()
            self.last_frame_stamp = None
            self.reset_confirmation('tracker_reset')
        fresh_result = (result is not None and result.epoch == epoch
                        and math.isfinite(now-result.received_at)
                        and -.05 <= now-result.received_at <= self.max_age_s
                        and (self.sequence is None or result.frame_id > self.sequence))
        historical_evidence = {}
        if fresh_result:
            self.bindings.observe(result.faces, result.bodies, now=result.received_at)
            historical_evidence = {b.track_id: self.has_face_evidence(
                b, result.faces, result.bodies, now=result.received_at, not_after=result.received_at)
                for b in result.bodies}
        self.bindings.observe(faces, bodies, now=now if observed_at is None else observed_at)
        for identity in self.latched:
            current = [b for b in bodies if b.track_id == identity]
            if (len(current) != 1 or overlap(self.latched_bodies[identity], current[0]) < .5
                    or not self.unique_face(current[0], faces, bodies)
                    or any(b.track_id != identity and overlap(b, current[0]) > .35 for b in bodies)):
                self.latched[identity] = None
                self.release_barriers[identity] = now if observed_at is None else observed_at
            else:
                self.latched_bodies[identity] = current[0]
        if self.candidate is not None:
            current = [b for b in bodies if b.track_id == self.candidate]
            if (len(current) != 1 or self.candidate_body is None
                    or overlap(self.candidate_body, current[0]) < .5
                    or not self.has_face_evidence(current[0], faces, bodies, now=now)):
                self.reject_uncertain('current_association_lost')
        if result is None:
            if self.last_stamp is not None and now-self.last_stamp > self.max_gap_s:
                self.reject_uncertain('gesture_gap')
            return None
        age = now-result.received_at
        if (result.epoch != epoch or not math.isfinite(age) or not -.05 <= age <= self.max_age_s):
            self.reject_uncertain('gesture_stale')
            return None
        if self.sequence is not None and result.frame_id <= self.sequence:
            return None
        self.sequence = result.frame_id
        if self.last_frame_stamp is not None:
            if result.received_at < self.last_frame_stamp:
                self.reject_uncertain('gesture_time_reversed')
                return None
            if result.received_at-self.last_frame_stamp > self.max_gap_s:
                self.reject_uncertain('gesture_gap')
        self.last_frame_stamp = result.received_at
        owners = set()
        owner_bodies = {}
        evidence = []
        for hand in result.hands:
            if (hand.label != SELECTION_GESTURE or hand.score < self.confidence or hand.w <= 0 or hand.h <= 0
                    or not all(math.isfinite(v) for v in (hand.x, hand.y, hand.w, hand.h, hand.score))):
                continue
            matched = self.owner(hand, result.bodies, result.poses)
            evidence.extend(self.pose_matcher.evidence)
            if len(matched) != 1:
                self.reject_uncertain('owner_ambiguous' if matched else 'pose_owner_unavailable')
                self.debug['owner_evidence'] = evidence
                return None
            old = matched[0]
            current = [b for b in bodies if b.track_id == old.track_id]
            if len(current) != 1 or overlap(old, current[0]) < .5:
                self.reject_uncertain('track_changed')
                return None
            body = current[0]
            if any(b.track_id != body.track_id and overlap(b, body) > .35 for b in bodies):
                self.reject_uncertain('owner_ambiguous')
                return None
            if (not historical_evidence.get(old.track_id, False)
                    or not self.has_face_evidence(body, faces, bodies, now=now)):
                self.reject_uncertain('face_body_unavailable')
                return None
            owners.add(body.track_id)
            owner_bodies[body.track_id] = body
        stamp = result.received_at
        for identity in list(self.latched):
            if identity in owners:
                self.latched[identity] = None
                if overlap(self.latched_bodies[identity], owner_bodies[identity]) >= .5:
                    self.latched_bodies[identity] = owner_bodies[identity]
            else:
                current = [b for b in bodies if b.track_id == identity]
                old = [b for b in result.bodies if b.track_id == identity]
                visible = (len(current) == len(old) == 1 and overlap(old[0], current[0]) >= .5
                           and overlap(self.latched_bodies[identity], current[0]) >= .5
                           and self.unique_face(current[0], faces, bodies)
                           and self.unique_face(old[0], result.faces, result.bodies)
                           and not any(b.track_id != identity and overlap(b, current[0]) > .35 for b in bodies))
                # Losing the person's box is not evidence that they lowered a hand.
                if not visible or stamp < self.release_barriers.get(identity, float('-inf')):
                    self.latched[identity] = None
                elif self.latched[identity] is None:
                    self.latched[identity] = stamp
                    self.latched_bodies[identity] = current[0]
                elif stamp-self.latched[identity]+1e-9 >= self.release_s:
                    del self.latched[identity]
                    del self.latched_bodies[identity]
                    self.release_barriers.pop(identity, None)
                else:
                    self.latched_bodies[identity] = current[0]
        if len(owners) != 1:
            # Only a missing hand on a continuously identified person may occupy
            # a negative slot; uncertain ownership must never become a vote.
            if not owners and self.window_frames and self.candidate is not None:
                old = [b for b in result.bodies if b.track_id == self.candidate]
                current = [b for b in bodies if b.track_id == self.candidate]
                continuous = (len(old) == len(current) == 1
                              and overlap(old[0], current[0]) >= .5
                              and historical_evidence.get(self.candidate, False)
                              and self.has_face_evidence(current[0], faces, bodies, now=now))
                if continuous:
                    self.candidate_body = current[0]
                    self.record_confirmation(stamp, False, evidence)
                    return None
            self.reset_confirmation('multiple_ok' if owners else 'no_ok')
            return None
        identity = next(iter(owners))
        if identity in self.latched or stamp < self.cooldown_until:
            self.reset_confirmation('release_required' if identity in self.latched else 'cooldown')
            return None
        if (self.candidate != identity or self.last_stamp is None
                or stamp-self.last_stamp > self.max_gap_s or stamp < self.last_stamp
                or self.candidate_body is not None and overlap(self.candidate_body, owner_bodies[identity]) < .5):
            self.reset_confirmation('new_candidate')
            self.candidate, self.since = identity, stamp
        self.candidate_body = owner_bodies[identity]
        self.record_confirmation(stamp, True, evidence)
        if stamp-self.since+1e-9 >= self.hold_s and self.count >= self.confirm_frames:
            self.latched[identity] = None
            self.latched_bodies[identity] = owner_bodies[identity]
            self.cooldown_until = stamp+self.cooldown_s
            self.reset_confirmation('ok_confirmed')
            self.debug['person_track_id'] = identity
            self.debug['owner_evidence'] = evidence
            return identity
        return None
