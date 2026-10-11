import importlib
import importlib.util
from pathlib import Path
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dummy.face_person_selector import FacePersonSelector
from dummy.person_lock_tracker import Candidate
from dummy.yolo_person_tracker import PersonTrack
from dummy.ok_gesture import GestureFrame, HandGesture, OkSwitch


def pose_api():
    assert importlib.util.find_spec('dummy.person_pose') is not None, 'pose ownership is missing'
    return importlib.import_module('dummy.person_pose')


def pose(body, wrist=(330, 190), confidence=.95):
    points = [(0., 0., 0.)] * 17
    shoulder = (body.x+body.w*.5, body.y+body.h*.35)
    elbow = ((shoulder[0]+wrist[0])/2, (shoulder[1]+wrist[1])/2)
    points[5], points[7], points[9] = (*shoulder, confidence), (*elbow, confidence), (*wrist, confidence)
    return pose_api().PersonPose(body.x, body.y, body.w, body.h, .95, tuple(points))


def test_projected_hand_over_background_person_belongs_to_foreground_arm():
    background = PersonTrack(1, 250, 200, 140, 110, .9)
    foreground = PersonTrack(2, 270, 40, 300, 350, .9)
    hand = HandGesture(300, 165, 80, 90, .95, 'palm')
    matcher = pose_api().PoseOwnerMatcher({})
    assert matcher.owners(hand, [pose(foreground)], [background, foreground]) == [foreground]


@pytest.mark.parametrize('confidence,wrist', [(.1, (330, 190)), (.95, (600, 400)), (.95, (float('nan'), 190))])
def test_missing_or_remote_wrist_never_falls_back_to_body_rectangle(confidence, wrist):
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    matcher = pose_api().PoseOwnerMatcher({})
    assert matcher.owners(HandGesture(300, 165, 80, 90, .95, 'palm'),
                          [pose(body, wrist, confidence)], [body]) == []


def test_pose_matching_two_body_ids_is_rejected():
    a = PersonTrack(1, 270, 40, 300, 350, .9)
    b = PersonTrack(2, 275, 40, 300, 350, .9)
    assert pose_api().PoseOwnerMatcher({}).owners(
        HandGesture(300, 165, 80, 90, .95, 'palm'), [pose(a)], [a, b]) == []


def test_ambiguous_competing_arm_vetoes_an_otherwise_unique_owner():
    a = PersonTrack(1, 100, 40, 200, 350, .9)
    duplicate = PersonTrack(3, 105, 40, 200, 350, .9)
    b = PersonTrack(2, 310, 40, 200, 350, .9)
    matcher = pose_api().PoseOwnerMatcher({})
    assert matcher.owners(HandGesture(270, 165, 80, 90, .95, 'palm'),
                          [pose(a), pose(b)], [a, duplicate, b]) == []


def test_two_people_with_wrists_in_one_hand_box_remain_ambiguous():
    a = PersonTrack(1, 100, 40, 200, 350, .9)
    b = PersonTrack(2, 310, 40, 200, 350, .9)
    owners = pose_api().PoseOwnerMatcher({}).owners(
        HandGesture(270, 165, 80, 90, .95, 'palm'), [pose(a), pose(b)], [a, b])
    assert {p.track_id for p in owners} == {1, 2}


def test_pose_is_only_computed_on_the_same_frame_when_ok_is_detected():
    from dummy.ok_gesture import GestureWorker
    assert 'pose_detector' in __import__('inspect').signature(GestureWorker).parameters
    # Directly exercise the production worker, never a camera or motion adapter.
    import threading
    calls = []
    class Hands:
        def detect(self, frame):
            return [HandGesture(0, 0, 5, 5, .9, 'palm')] if frame[0, 0, 0] else []
    class Poses:
        def detect(self, frame):
            calls.append(frame)
            return []
    worker = GestureWorker(Hands(), pose_detector=Poses(), hz=100)
    worker.start()
    try:
        for sequence in (1, 2):
            image = np.full((8, 8, 3), sequence-1, dtype=np.uint8)
            worker.submit(image, sequence, time.time(), 0, [], [])
            deadline = time.monotonic()+2
            while (worker.latest() is None or worker.latest().frame_id != sequence) and time.monotonic()<deadline:
                time.sleep(.005)
            assert worker.latest().frame_id == sequence
        assert len(calls) == 1 and calls[0] is image
        assert worker.latest().poses == ()
    finally:
        worker.close()
    assert not any(t.name == 'dummy-ok' and t.is_alive() for t in threading.enumerate())


def test_ok_confirmation_survives_short_face_dropout_but_not_expired_binding():
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    face = Candidate(430, 110, 50, 60, .95, 'face')
    hand = HandGesture(300, 165, 80, 90, .95, 'palm')
    s = OkSwitch({'hold_s': .5, 'face_binding_ttl_s': .8})
    for i, stamp in enumerate([1., 1.2, 1.4, 1.6]):
        faces = [face] if i == 0 else []
        result = GestureFrame(i+1, stamp, 0, (hand,), (body,), tuple(faces), 2., poses=(pose(body),))
        selected = s.update(result, now=stamp+.01, bodies=[body], faces=faces, epoch=0)
    assert selected == 2
    late = GestureFrame(10, 3, 0, (hand,), (body,), (), 2., poses=(pose(body),))
    assert s.update(late, now=3.01, bodies=[body], faces=[], epoch=0) is None
    assert s.debug['reason'] == 'face_body_unavailable'


def test_unknown_person_without_face_binding_cannot_be_selected():
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    s = OkSwitch({})
    result = GestureFrame(1, 1, 0, (HandGesture(300, 165, 80, 90, .95, 'palm'),),
                          (body,), (), 2., poses=(pose(body),))
    assert s.update(result, now=1.01, bodies=[body], faces=[], epoch=0) is None
    assert s.debug['reason'] == 'face_body_unavailable'


def test_current_clean_face_cannot_repair_ambiguous_historical_face_frame():
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    face = Candidate(430, 110, 50, 60, .95, 'face')
    second = Candidate(380, 110, 40, 50, .95, 'face')
    hand = HandGesture(300, 165, 80, 90, .95, 'palm')
    s = OkSwitch({})
    for i, stamp in enumerate([1., 1.2, 1.4, 1.6]):
        result = GestureFrame(i+1, stamp, 0, (hand,), (body,), (face, second), 2., poses=(pose(body),))
        assert s.update(result, now=stamp+.01, bodies=[body], faces=[face], epoch=0) is None
    assert s.debug['reason'] == 'face_body_unavailable'


def test_duplicate_gesture_result_does_not_hide_current_body_loss():
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    face = Candidate(430, 110, 50, 60, .95, 'face')
    hand = HandGesture(300, 165, 80, 90, .95, 'palm')
    result = GestureFrame(1, 1, 0, (hand,), (body,), (face,), 2., poses=(pose(body),))
    s = OkSwitch({})
    s.update(result, now=1.01, bodies=[body], faces=[face], epoch=0)
    s.update(result, now=1.05, bodies=[], faces=[], epoch=0)
    assert s.candidate is None and not s.bindings.records


def test_future_face_binding_cannot_authorize_an_older_missing_face_frame():
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    face = Candidate(430, 110, 50, 60, .95, 'face')
    hand = HandGesture(300, 165, 80, 90, .95, 'palm')
    s = OkSwitch({'hold_s': .1, 'confirm_frames': 2})
    s.update(None, now=1.2, bodies=[body], faces=[face], epoch=0)
    result = GestureFrame(1, 1., 0, (hand,), (body,), (), 2., poses=(pose(body),))
    assert s.update(result, now=1.21, bodies=[body], faces=[face], epoch=0) is None
    assert s.debug['reason'] == 'face_body_unavailable'


def test_face_seen_between_gesture_results_primes_future_missing_face_binding():
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    face = Candidate(430, 110, 50, 60, .95, 'face')
    hand = HandGesture(300, 165, 80, 90, .95, 'palm')
    s = OkSwitch({'hold_s': .1, 'confirm_frames': 2})
    s.update(None, now=1., bodies=[body], faces=[face], epoch=0)
    for i, stamp in enumerate([1.1, 1.3]):
        result = GestureFrame(i+1, stamp, 0, (hand,), (body,), (), 2., poses=(pose(body),))
        selected = s.update(result, now=stamp+.01, bodies=[body], faces=[], epoch=0)
    assert selected == 2


def test_hand_confidence_threshold_does_not_raise_face_binding_threshold():
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    face = Candidate(430, 110, 50, 60, .81, 'face')
    hand = HandGesture(300, 165, 80, 90, .99, 'palm')
    s = OkSwitch({'min_confidence': .95, 'face_min_confidence': .8})
    assert s.unique_face(body, [face], [body]), 'hand and face thresholds must be independent'
    selected = None
    for i, stamp in enumerate([1., 1.2, 1.4, 1.6]):
        result = GestureFrame(i+1, stamp, 0, (hand,), (body,), (face,), 2., poses=(pose(body),))
        selected = s.update(result, now=stamp+.01, bodies=[body], faces=[face], epoch=0)
    assert selected == 2


def test_selector_can_switch_using_recent_confirmed_face_binding_then_body_anchor():
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    face = Candidate(430, 110, 50, 60, .95, 'face')
    selector = FacePersonSelector({'face_lock': {'confirm_frames': 1}, 'ok_switch': {'face_binding_ttl_s': .8}})
    assert hasattr(selector, 'observe_bindings'), 'recent face binding is missing'
    selector.observe_bindings([face], [body], now=1.)
    assert selector.switch_to_person(2, [], [body], now=1.5)
    result = selector.update([], [body], now=1.5, frame_size=(640, 480))
    assert result.found and result.kind == 'face_person_body'
    assert selector.last_debug['selection_event']['type'] == 'ok'


def test_expired_or_discontinuous_binding_cannot_authorize_switch():
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    face = Candidate(430, 110, 50, 60, .95, 'face')
    selector = FacePersonSelector({'ok_switch': {'face_binding_ttl_s': .8}})
    assert hasattr(selector, 'observe_bindings')
    selector.observe_bindings([face], [body], now=1.)
    assert not selector.switch_to_person(2, [], [body], now=2.)
    shifted = PersonTrack(2, 20, 40, 150, 350, .9)
    assert not selector.switch_to_person(2, [], [shifted], now=1.4)


def test_selector_marks_automatic_reacquisition_separately_from_ok():
    body = PersonTrack(1, 100, 80, 100, 350, .9)
    face = Candidate(150, 120, 25, 30, .95, 'face')
    selector = FacePersonSelector({'face_lock': {'confirm_frames': 1}})
    selector.update([face], [body], now=1., frame_size=(640, 480))
    assert 'selection_event' in selector.last_debug
    assert selector.last_debug['selection_event']['type'] == 'auto_initial'
    selector.update([], [], now=2.2, frame_size=(640, 480))
    selector.update([face], [body], now=2.3, frame_size=(640, 480))
    assert selector.last_debug['selection_event']['type'] == 'auto_reacquire'


@pytest.mark.parametrize('interruption', ['missing', 'overlap'])
def test_body_anchor_requires_face_reconfirmation_after_identity_continuity_break(interruption):
    body = PersonTrack(1, 100, 80, 100, 350, .9)
    face = Candidate(150, 120, 25, 30, .95, 'face')
    selector = FacePersonSelector({'face_lock': {'confirm_frames': 1}})
    selector.update([face], [body], now=1., frame_size=(640, 480))
    uncertain = [] if interruption == 'missing' else [body, PersonTrack(2, 105, 80, 100, 350, .9)]
    assert not selector.update([], uncertain, now=1.1, frame_size=(640, 480)).found
    assert not selector.update([], [body], now=1.2, frame_size=(640, 480)).found
    assert selector.last_debug['rejected'] == 'identity_reconfirmation_required'
    assert selector.update([face], [body], now=1.3, frame_size=(640, 480)).found
    assert selector.update([], [body], now=1.4, frame_size=(640, 480)).found


def test_keyword_busy_inhibits_automatic_identity_reacquisition():
    body = PersonTrack(1, 100, 80, 100, 350, .9)
    face = Candidate(150, 120, 25, 30, .95, 'face')
    other = PersonTrack(2, 400, 80, 100, 350, .9)
    other_face = Candidate(450, 120, 25, 30, .95, 'face')
    selector = FacePersonSelector({'face_lock': {'confirm_frames': 1}})
    selector.update([face], [body], now=1., frame_size=(640, 480))
    assert 'selection_allowed' in __import__('inspect').signature(selector.update).parameters
    selected_generation = selector.generation
    target = selector.update([other_face], [other], now=2.2, frame_size=(640, 480), selection_allowed=False)
    assert not target.found and selector.track_id == 1 and selector.generation == selected_generation
    target = selector.update([other_face], [other], now=2.3, frame_size=(640, 480), selection_allowed=True)
    assert target.found and selector.track_id == 2


@pytest.mark.parametrize('interruption', ['stale', 'unavailable'])
def test_production_camera_gap_invalidates_body_anchor_without_invalidating_duplicates(interruption):
    import threading
    from types import SimpleNamespace
    from dummy.vision_service_tracker import VisionServiceTracker
    from dummy.tracker import Target
    body = PersonTrack(1, 100, 80, 100, 350, .9)
    face = Candidate(150, 120, 25, 30, .95, 'face')
    selector = FacePersonSelector({'face_lock': {'confirm_frames': 1}})
    now = time.time()
    assert selector.update([face], [body], now=now-.1, frame_size=(640, 480)).found
    tracker = VisionServiceTracker.__new__(VisionServiceTracker)
    tracker.face_person, tracker.ok_switch = selector, OkSwitch({})
    tracker._ok_lock = threading.Lock()
    tracker.width, tracker.height = 640, 480
    tracker.max_frame_age_s, tracker.face_only, tracker.allow_health_fallback = .5, True, False
    tracker.last_debug, tracker._last_frame_sequence = {}, 1
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    packet = (image, None, 1, now)
    tracker.reader = SimpleNamespace(latest_packet=lambda: packet)
    assert tracker.read_frame()[0].kind == 'vision_frame_duplicate'
    assert selector.update([], [body], now=now, frame_size=(640, 480)).found
    packet = (image, None, 2, now-1) if interruption == 'stale' else (None, 'no frame', 2, now)
    assert not tracker.read_frame()[0].found
    packet = (image, None, 3, now+.01)
    tracker._read_face_target = lambda _frame, stamp: selector.update([], [body], now=stamp, frame_size=(640, 480))
    assert not tracker.read_frame()[0].found
    assert selector.last_debug['rejected'] == 'identity_reconfirmation_required'
    assert selector.update([face], [body], now=now+.02, frame_size=(640, 480)).found


@pytest.mark.parametrize('missing_result', [False, True])
def test_current_body_loss_interrupts_latch_release_even_without_new_gesture(missing_result):
    body = PersonTrack(2, 270, 40, 300, 350, .9)
    face = Candidate(430, 110, 50, 60, .95, 'face')
    hand = HandGesture(300, 165, 80, 90, .95, 'palm')
    s = OkSwitch({'hold_s': .1, 'confirm_frames': 2})
    def step(sequence, stamp, hands):
        result = GestureFrame(sequence, stamp, 0, tuple(hands), (body,), (face,), 2., poses=(pose(body),))
        return s.update(result, now=stamp+.001, bodies=[body], faces=[face], epoch=0)
    step(1, 2., [hand])
    assert step(2, 2.2, [hand]) == 2
    step(3, 2.3, [])
    duplicate = GestureFrame(3, 2.3, 0, (), (body,), (face,), 2.)
    s.update(None if missing_result else duplicate, now=2.45, bodies=[], faces=[], epoch=0)
    assert s.latched[2] is None
    # A delayed pre-loss frame must not backdate the new release interval.
    step(4, 2.4, [])
    assert s.latched[2] is None
    step(5, 2.61, [])
    assert 2 in s.latched


def test_loss_telemetry_reports_observation_expiry_instead_of_detector_loss():
    from dummy.person_follow.runtime import PersonFollowRuntime
    from dummy.person_follow.telemetry import observation_snapshot
    from dummy.tracker import Target
    runtime = PersonFollowRuntime(None)
    runtime.publish(Target(True, 320, 240, 640, 480, .9, 'face_person_face', time.time()-1),
                    debug={'follow_target': 'face_person', 'control_source': 'FACE', 'bbox': [300, 220, 40, 40]})
    state = observation_snapshot(runtime)[1]
    assert state.get('loss_reason') == 'observation_expired'
    assert state['target']['found'] and state['control_source'] == 'LOST'


def test_stale_camera_telemetry_preserves_actual_receive_age():
    from dummy.person_follow.runtime import PersonFollowRuntime
    from dummy.person_follow.telemetry import observation_snapshot
    from dummy.tracker import Target
    runtime = PersonFollowRuntime(None)
    runtime.publish(Target(False, kind='vision_frame_stale', ts=time.time()),
                    debug={'follow_target': 'face_person', 'frame_received_at': time.time()-1.2})
    state = observation_snapshot(runtime)[1]
    assert state.get('loss_reason') == 'vision_frame_stale'
    assert state['receive_age_ms'] >= 1200
