import asyncio
import importlib
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dummy.face_person_selector import FacePersonSelector
from dummy.person_lock_tracker import Candidate
from dummy.yolo_person_tracker import PersonTrack
from dummy.person_pose import PersonPose


def scene():
    return ([Candidate(150, 120, 25, 30, .95, 'face'),
             Candidate(450, 120, 25, 30, .95, 'face')],
            [PersonTrack(1, 100, 80, 100, 350, .9),
             PersonTrack(2, 400, 80, 100, 350, .9)])


def poses(bodies):
    result = []
    for b in bodies:
        points = [(0., 0., 0.)]*17
        points[5], points[7], points[9] = (b.x+50, b.y+45, .95), (b.x+45, b.y+80, .95), (b.x+40, b.y+115, .95)
        result.append(PersonPose(b.x, b.y, b.w, b.h, .95, tuple(points)))
    return tuple(result)


def selector():
    return FacePersonSelector({'face_lock': {'confirm_frames': 1}})


def test_explicit_switch_requires_unique_face_body_and_blends_then_tracks_body():
    s = selector()
    faces, bodies = scene()
    s.update(faces[:1], bodies, now=1, frame_size=(640, 480))
    old = s.last_point
    assert s.switch_to_person(2, faces, bodies, now=1.1)
    target = s.update(faces, bodies, now=1.1, frame_size=(640, 480))
    assert s.track_id == 2 and s.generation == 2
    assert (target.u, target.v) == pytest.approx(old)
    s.update(faces, bodies, now=1.3, frame_size=(640, 480))
    s.update(faces, bodies, now=1.4, frame_size=(640, 480))
    target = s.update([], bodies, now=1.5, frame_size=(640, 480))
    assert target.kind == 'face_person_body' and target.u > old[0]
    assert not s.switch_to_person(1, [], bodies, now=2.5)  # Cached face binding expired.
    assert s.track_id == 2 and s.generation == 2


def api():
    return importlib.import_module('dummy.ok_gesture')


def hand(owner=2, score=.95):
    return api().HandGesture(430 if owner == 2 else 130, 180, 20, 30, score, 'palm')


def frame(sequence, timestamp, hands, epoch=0):
    faces, bodies = scene()
    return api().GestureFrame(sequence, timestamp, epoch, tuple(hands), tuple(bodies), tuple(faces), 12.,
                              poses=poses(bodies))


def tick(s, sequence, timestamp, hands, **kwargs):
    faces, bodies = scene()
    return s.update(frame(sequence, timestamp, hands), now=timestamp+.02,
                    bodies=bodies, faces=faces, epoch=0, **kwargs)


def test_ok_hold_switches_once_then_requires_release_before_another_event():
    s = api().OkSwitch({})
    for i, t in enumerate([1, 1.2, 1.4]):
        assert tick(s, i+1, t, [hand()]) is None
    assert tick(s, 4, 1.6, [hand()]) == 2
    assert tick(s, 5, 1.8, [hand()]) is None
    assert tick(s, 6, 2.5, [hand()]) is None
    tick(s, 7, 2.7, [])
    tick(s, 8, 3.0, [])
    tick(s, 9, 3.2, [hand()])
    tick(s, 10, 3.4, [hand()])
    tick(s, 11, 3.6, [hand()])
    assert tick(s, 12, 3.8, [hand()]) == 2


def test_keyword_epoch_preserves_held_gesture_latch():
    s = api().OkSwitch({'hold_s': .1, 'confirm_frames': 2})
    faces, bodies = scene()
    def step(sequence, stamp, epoch):
        return s.update(frame(sequence, stamp, [hand()], epoch), now=stamp+.01,
                        bodies=bodies, faces=faces, epoch=epoch, scene_epoch=0)
    step(1, 1, 0)
    assert step(2, 1.2, 0) == 2
    step(3, 3, 1)
    assert step(4, 3.2, 1) is None


def test_same_id_jump_between_results_restarts_confirmation():
    s = api().OkSwitch({'hold_s': .3, 'confirm_frames': 2})
    tick(s, 1, 1, [hand()])
    faces, bodies = scene()
    jumped = [bodies[0], PersonTrack(2, 250, 80, 100, 350, .9)]
    newfaces = [faces[0], Candidate(300, 120, 25, 30, .95, 'face')]
    result = api().GestureFrame(2, 1.3, 0, (api().HandGesture(280, 180, 20, 30, .95, 'palm'),),
                                tuple(jumped), tuple(newfaces), 2, poses=poses(jumped))
    assert s.update(result, now=1.31, bodies=jumped, faces=newfaces, epoch=0) is None
    assert s.debug['progress'] == 0


def test_ambiguity_interrupts_release_evidence():
    s = api().OkSwitch({'hold_s': .1, 'confirm_frames': 2})
    tick(s, 1, 1, [hand()])
    assert tick(s, 2, 1.2, [hand()]) == 2
    tick(s, 3, 1.8, [])
    ambiguous = api().HandGesture(300, 180, 20, 30, .95, 'palm')
    tick(s, 4, 2., [ambiguous])
    tick(s, 5, 2.11, [])
    assert tick(s, 6, 2.2, [hand()]) is None
    assert tick(s, 7, 2.4, [hand()]) is None


def test_reader_close_failure_still_closes_ok_worker_and_face_detectors():
    from dummy.vision_service_tracker import VisionServiceTracker
    tracker = VisionServiceTracker.__new__(VisionServiceTracker)
    closed = []
    def fail():
        raise RuntimeError('reader failure')
    tracker.reader = SimpleNamespace(close=fail)
    tracker.ok_worker = SimpleNamespace(close=lambda: closed.append('ok'))
    tracker._closed = threading.Event()
    tracker._lifecycle_lock = threading.Lock()
    tracker.yunet_face = SimpleNamespace(close=lambda: closed.append('face'))
    tracker.mediapipe_face = None
    with pytest.raises(RuntimeError):
        tracker.close()
    assert closed == ['ok', 'face']


def test_detection_join_timeout_stops_background_worker():
    from dummy.person_follow.runtime import TrackerWorker
    closed = []
    tracker = SimpleNamespace(reader=SimpleNamespace(close=lambda: None),
                              close_background_workers=lambda: closed.append('ok'),
                              close=lambda: closed.append('all'))
    worker = TrackerWorker(tracker, lambda *_args: None, .1)
    worker.thread = SimpleNamespace(join=lambda **_kwargs: None, is_alive=lambda: True)
    with pytest.raises(RuntimeError, match='did not stop'):
        worker.close()
    assert closed == ['ok']


def test_background_close_failure_and_join_timeout_still_close_reader():
    from dummy.person_follow.runtime import TrackerWorker
    closed = []
    def fail_background():
        raise RuntimeError('inference did not stop')
    tracker = SimpleNamespace(reader=SimpleNamespace(close=lambda: closed.append('reader')),
                              close_background_workers=fail_background,
                              close=lambda: closed.append('all'))
    worker = TrackerWorker(tracker, lambda *_args: None, .1)
    worker.thread = SimpleNamespace(join=lambda **_kwargs: None, is_alive=lambda: True)
    with pytest.raises(RuntimeError):
        worker.close()
    assert closed == ['reader']


def test_pre_resume_frame_is_not_submitted_with_new_keyword_epoch():
    from dummy.vision_service_tracker import VisionServiceTracker
    tracker = VisionServiceTracker.__new__(VisionServiceTracker)
    tracker._ok_lock = threading.Lock()
    tracker._ok_allowed, tracker._ok_epoch, tracker._person_epoch = True, 0, 0
    tracker._ok_resume_after = 0
    tracker.face_person = None
    tracker.ok_switch = api().OkSwitch({})
    submitted = []
    tracker.ok_worker = SimpleNamespace(error=None, latest=lambda: None,
                                       submit=lambda *_args: submitted.append(True))
    tracker.ok_error = None
    tracker.ok_enabled = True
    tracker._last_frame_sequence = 1
    faces, bodies = scene()
    received = time.time()-.01
    tracker.set_switching_allowed(False)
    tracker.set_switching_allowed(True)
    debug = tracker._process_ok(np.zeros((2, 2, 3), dtype=np.uint8), faces, bodies, received)
    assert debug['reason'] == 'keyword_frame_before_resume'
    assert not submitted


def test_duplicate_stale_epoch_busy_and_two_owners_never_switch():
    s = api().OkSwitch({})
    tick(s, 1, 1., [hand()])
    for now in (1.2, 1.4, 1.6):
        faces, bodies = scene()
        assert s.update(frame(1, 1., [hand()]), now=now, bodies=bodies,
                        faces=faces, epoch=0) is None
    assert tick(s, 2, 1.7, [hand()], allowed=False) is None
    for i, t in enumerate([1.8, 2, 2.2, 2.4]):
        assert tick(s, 3+i, t, [hand(1), hand(2)]) is None
    faces, bodies = scene()
    assert s.update(frame(20, 3., [hand()], epoch=1), now=3.02,
                    bodies=bodies, faces=faces, epoch=0) is None
    assert s.update(frame(21, 3., [hand()]), now=4.,
                    bodies=bodies, faces=faces, epoch=0) is None


def test_no_face_ambiguous_hand_or_discontinuous_body_rejects():
    s = api().OkSwitch({'hold_s': .1, 'confirm_frames': 2})
    faces, bodies = scene()
    from dataclasses import replace
    assert s.update(replace(frame(1, 1, [hand()]), faces=()), now=1.02, bodies=bodies,
                    faces=[], epoch=0) is None
    assert s.debug['reason'] == 'face_body_unavailable'
    crossed = bodies + [PersonTrack(3, 425, 80, 100, 350, .9)]
    assert s.update(frame(2, 1.2, [hand()]), now=1.22, bodies=crossed,
                    faces=faces, epoch=0) is None
    assert s.debug['reason'] in ('owner_ambiguous', 'track_changed')
    displaced = [bodies[0], PersonTrack(2, 50, 80, 100, 350, .9)]
    assert s.update(frame(3, 1.4, [hand()]), now=1.42, bodies=displaced,
                    faces=faces, epoch=0) is None
    assert s.debug['reason'] == 'track_changed'


def test_worker_replaces_pending_frame_and_closes_without_camera_or_robot():
    entered, release = threading.Event(), threading.Event()
    seen = []
    class Detector:
        def detect(self, image):
            seen.append(int(image[0, 0, 0]))
            if len(seen) == 1:
                entered.set()
                assert release.wait(2)
            return []
    w = api().GestureWorker(Detector(), hz=100)
    w.start()
    try:
        faces, bodies = scene()
        for value in [1]:
            w.submit(np.full((2, 2, 3), value, dtype=np.uint8), value, time.time(), 0, bodies, faces)
        assert entered.wait(2)
        for value in [2, 3]:
            w.submit(np.full((2, 2, 3), value, dtype=np.uint8), value, time.time(), 0, bodies, faces)
        release.set()
        deadline = time.monotonic()+2
        while len(seen) < 2 and time.monotonic() < deadline:
            time.sleep(.01)
        assert seen == [1, 3]
    finally:
        release.set()
        w.close()
    assert not w.thread.is_alive()


def test_yolo_adapter_rejects_wrong_labels_and_parses_palm_only(tmp_path):
    a = api()
    wrong = SimpleNamespace(names={0: 'person'})
    with pytest.raises(ValueError, match='palm'):
        a.HagridDetector({}, model=wrong)
    model = SimpleNamespace(names={0: 'palm', 1: 'ok'})
    boxes = SimpleNamespace(xyxy=np.array([[10, 20, 30, 50], [1, 2, 5, 6]]),
                            conf=np.array([.9, .99]), cls=np.array([0, 1]))
    model.predict = lambda *_args, **_kwargs: [SimpleNamespace(boxes=boxes)]
    d = a.HagridDetector({}, model=model)
    assert d.detect(np.zeros((100, 100, 3), dtype=np.uint8)) == [a.HandGesture(10, 20, 20, 30, .9, 'palm')]


def test_runtime_resets_error_on_selection_generation_without_widening_envelope():
    from dummy.person_follow.runtime import PersonFollowRuntime
    from dummy.tracker import Target
    from dummy.image_jacobian_servo import ImageJacobianServo
    config = {'image_jacobian_servo': {'enabled': True, 'axes': [
        {'joint_index': 0, 'px_per_deg': [4, 0], 'max_excursion_deg': 85}]}}
    servo = ImageJacobianServo(config)
    r = PersonFollowRuntime(None, config=config, servo=servo)
    servo._last_error = (200, 0)
    r.publish(Target(True, 320, 240, 640, 480, .9, 'face_person_face', time.time()),
              debug={'selection_generation': 2})
    asyncio.run(r.step())
    assert r.metrics['selection_generation'] == 2
    assert servo._base_joints == [0]*6
    assert servo._last_error == (0, 0)


def test_keyword_inhibits_selection_and_discards_during_action_observation():
    from dummy.person_follow.runtime import PersonFollowRuntime
    from dummy.tracker import Target
    r = PersonFollowRuntime(None, config={'gestures': {'nod': {'keyframes': []}}})
    seen = []
    r._selection_gate = seen.append
    async def gesture(*_args):
        r.publish(Target(True, 320, 240, 640, 480, .9, 'face_person_face', time.time()))
        return True
    r._gesture = gesture
    r.queue_keyword('nod')
    assert asyncio.run(r.step())
    assert seen == [False, True]
    assert r._consumed == r._sequence


def test_low_confidence_and_confirmation_gap_do_not_accumulate_hold_time():
    s = api().OkSwitch({})
    tick(s, 1, 1., [hand()])
    assert tick(s, 2, 1.2, [hand(score=.79)]) is None
    assert tick(s, 3, 1.5, [hand()]) is None
    assert tick(s, 4, 1.9, [hand()]) is None
    assert s.debug['progress'] == 0


def test_tracker_consumes_same_source_async_ok_result_and_keyword_epoch(monkeypatch):
    import dummy.vision_service_tracker as module
    from dummy.tracker import Target
    faces, bodies = scene()
    class FaceDetector:
        def __init__(self):
            self.faces = faces[:1]
        def detect_all(self, image):
            return [(Target(True, f.u, f.v, 640, 480, f.score, f.kind),
                     {'bbox': [f.u-f.w/2, f.v-f.h/2, f.w, f.h]}) for f in self.faces]
    class BodyDetector:
        inference_ms = 2
        epoch = 0
        def track(self, *_args, **_kwargs):
            return bodies
    detector = FaceDetector()
    monkeypatch.setattr(module, 'YuNetFaceDetector', lambda *_args, **_kwargs: detector)
    monkeypatch.setattr(module, 'YoloPersonTracker', lambda *_args, **_kwargs: BodyDetector())
    cfg = {'vision_service': {'follow_target': 'face', 'face_detector': 'yunet',
                             'mediapipe_face_enabled': False},
           'person_tracking': {'enabled': True}, 'face_lock': {'confirm_frames': 1},
           'ok_switch': {'enabled': True, 'hold_s': .1, 'confirm_frames': 2}}
    tracker = module.VisionServiceTracker(cfg)
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    now = time.time()
    tracker._last_frame_sequence = 1
    tracker._read_face_target(image, now-.2)
    assert tracker.face_person.track_id == 1
    detector.faces = faces
    pending = []
    result = api().GestureFrame(1, now-.15, 0, (hand(),), tuple(bodies), tuple(faces), 2, poses=poses(bodies))
    worker = SimpleNamespace(error=None, latest=lambda: result,
                             submit=lambda *args: pending.append(args))
    tracker.ok_worker = worker
    tracker._last_frame_sequence = 2
    tracker._read_face_target(image, now-.1)
    assert tracker.face_person.track_id == 1
    result = api().GestureFrame(2, now-.02, 0, (hand(),), tuple(bodies), tuple(faces), 2, poses=poses(bodies))
    tracker._last_frame_sequence = 3
    tracker._read_face_target(image, now)
    assert tracker.face_person.track_id == 2
    assert tracker.last_debug['ok_switch']['reason'] == 'switched'
    hand_preview = tracker.last_debug['ok_switch']['hands']
    assert len(hand_preview) == 1
    assert hand_preview[0]['source_frame_id'] == 2
    assert hand_preview[0]['projected'] is True
    assert tracker._last_frame_sequence == 3
    assert pending[-1][0] is image  # Reuse the existing frame, no second reader.
    tracker.set_switching_allowed(False)
    tracker._last_frame_sequence = 4
    tracker._read_face_target(image, now+.01)
    assert tracker.last_debug['ok_switch']['reason'] == 'keyword_busy'
    assert not tracker.last_target.found
    assert tracker.face_person.track_id == 2
    assert tracker.last_debug['rejected'] == 'keyword_busy'
    tracker._last_frame_sequence = 5
    detector.faces = faces[:1]
    tracker._read_face_target(image, now+2.)
    assert not tracker.last_target.found
    assert tracker.face_person.track_id == 2  # No automatic change while the gate is closed.
    tracker.set_switching_allowed(True)
    tracker._last_frame_sequence = 6
    tracker._read_face_target(image, now+2.01)
    assert tracker.last_debug['ok_switch']['reason'] == 'gesture_stale'
    assert tracker.last_target.found and tracker.face_person.track_id == 1


def test_worker_rate_is_not_accelerated_by_pending_frame_notifications():
    times = []
    class Detector:
        def detect(self, image):
            times.append(time.monotonic())
            return []
    worker = api().GestureWorker(Detector(), hz=8)
    worker.start()
    try:
        faces, bodies = scene()
        deadline = time.monotonic()+.5
        sequence = 0
        while time.monotonic() < deadline:
            sequence += 1
            worker.submit(np.zeros((2, 2, 3), dtype=np.uint8), sequence, time.time(), 0, bodies, faces)
            time.sleep(.01)
    finally:
        worker.close()
    assert 2 <= len(times) <= 5
    assert min(b-a for a, b in zip(times, times[1:])) >= .12


def test_absence_gap_does_not_rearm_a_held_gesture():
    s = api().OkSwitch({'hold_s': .1, 'confirm_frames': 2})
    tick(s, 1, 1, [hand()])
    assert tick(s, 2, 1.2, [hand()]) == 2
    tick(s, 3, 1.4, [])
    tick(s, 4, 2.2, [])  # No evidence of continuous release in this interval.
    assert tick(s, 5, 2.3, [hand()]) is None
    assert tick(s, 6, 2.5, [hand()]) is None


def test_person_out_of_view_is_not_evidence_of_gesture_release():
    s = api().OkSwitch({'hold_s': .1, 'confirm_frames': 2})
    tick(s, 1, 1, [hand()])
    assert tick(s, 2, 1.2, [hand()]) == 2
    for i, stamp in enumerate([1.8, 2., 2.2, 2.4]):
        missing = api().GestureFrame(i+3, stamp, 0, (), (), (), 2)
        assert s.update(missing, now=stamp+.01, bodies=[], faces=[], epoch=0) is None
    assert tick(s, 7, 3., [hand()]) is None
    assert tick(s, 8, 3.2, [hand()]) is None


def test_delayed_model_load_cannot_start_workers_after_shutdown(monkeypatch):
    import dummy.vision_service_tracker as module
    tracker = module.VisionServiceTracker.__new__(module.VisionServiceTracker)
    entered, release = threading.Event(), threading.Event()
    started = []
    def load(*_args):
        entered.set()
        assert release.wait(2)
        return object()
    monkeypatch.setattr(module, 'HagridDetector', load)
    monkeypatch.setattr(module, 'GestureWorker', lambda *_args, **_kwargs:
                        SimpleNamespace(start=lambda: started.append('ok'), close=lambda: None))
    tracker.ok_enabled, tracker.ok_options, tracker.ok_worker = True, {}, None
    tracker._closed = threading.Event()
    tracker._lifecycle_lock = threading.Lock()
    tracker.reader = SimpleNamespace(start=lambda: started.append('reader'),
                                     latest=lambda: (np.zeros((2, 2, 3)), None))
    thread = threading.Thread(target=tracker.open)
    thread.start()
    try:
        assert entered.wait(2)
        tracker.close_background_workers()
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert started == []


def test_same_id_replacement_cannot_release_another_persons_held_gesture():
    s = api().OkSwitch({'hold_s': .1, 'confirm_frames': 2})
    tick(s, 1, 1, [hand()])
    assert tick(s, 2, 1.2, [hand()]) == 2
    faces, bodies = scene()
    replaced = [bodies[0], PersonTrack(2, 20, 80, 70, 350, .9)]
    newfaces = [faces[0], Candidate(50, 120, 25, 30, .95, 'face')]
    for i, stamp in enumerate([1.8, 2, 2.2]):
        result = api().GestureFrame(i+3, stamp, 0, (), tuple(replaced), tuple(newfaces), 2)
        assert s.update(result, now=stamp+.01, bodies=replaced, faces=newfaces, epoch=0) is None
    assert tick(s, 6, 2.4, [hand()]) is None
    assert tick(s, 7, 2.6, [hand()]) is None
