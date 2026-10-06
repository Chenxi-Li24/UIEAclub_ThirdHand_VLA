import asyncio
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.face_person_selector import FacePersonSelector
from dummy.person_follow.runtime import PersonFollowRuntime
from dummy.person_follow.telemetry import observation_snapshot
from dummy.person_lock_tracker import Candidate
from dummy.vision_service_tracker import VisionServiceTracker
from dummy.yolo_person_tracker import PersonTrack, YoloPersonTracker
from dummy.tracker import Target


def face(u=250., v=125.):
    return Candidate(u, v, 25., 30., .9, "yunet_face")


def body(identity=7, x=200., y=100., w=100., h=300.):
    return PersonTrack(identity, x, y, w, h, .85)


def selector():
    return FacePersonSelector({"vision_service": {"face_detector": "yunet"},
                               "face_lock": {"confirm_frames": 1}})


def update(s, faces, bodies, now):
    return s.update(faces, bodies, now=now, frame_size=(640, 480))


def test_face_binds_id_and_body_uses_calibrated_head_not_torso():
    s = selector()
    assert update(s, [face()], [body()], 1).kind == "face_person_face"
    assert s.track_id == 7 and s.anchor == (.5, 25./300.)
    result = update(s, [], [body()], 1.1)
    assert result.kind == "face_person_body" and result.v == pytest.approx(125.)
    assert result.ts == 1.1 and s.last_debug["control_source"] == "BODY"


def test_body_continues_longer_than_face_loss_timeout_and_recovers_face():
    s = selector()
    update(s, [face()], [body()], 1)
    for now in (1.1, 1.8, 2.5, 3.2):
        assert update(s, [], [body()], now).found
    assert update(s, [face()], [body()], 3.3).kind == "face_person_face"
    assert s.track_id == 7 and s.generation == 1


def test_higher_score_other_person_cannot_steal_selected_id():
    s = selector()
    update(s, [face()], [body()], 1)
    result = update(s, [face(500)], [body(), body(8, x=450)], 1.1)
    assert result.kind == "face_person_body" and s.track_id == 7
    assert result.u == pytest.approx(250.)


def test_face_body_source_switch_is_continuous():
    s = selector()
    first = update(s, [face()], [body()], 1)
    second = update(s, [], [body(x=230)], 1.1)
    assert (second.u, second.v) == pytest.approx((first.u, first.v))
    third = update(s, [], [body(x=230)], 1.5)
    assert first.u < third.u < 281
    recovered = update(s, [face(285)], [body(x=230)], 1.6)
    assert (recovered.u, recovered.v) == pytest.approx((third.u, third.v))


def test_both_lost_never_produces_a_predicted_control_target():
    s = selector()
    update(s, [face()], [body()], 1)
    result = update(s, [], [], 1.1)
    assert not result.found and result.kind == "face_person_lost"
    assert s.last_seen == 1 and s.last_debug["control_source"] == "LOST"


def test_loss_timeout_allows_confirmed_reacquisition_of_another_person():
    s = selector()
    update(s, [face()], [body()], 1)
    assert not update(s, [face(500)], [body(8, x=450)], 1.2).found
    assert update(s, [face(500)], [body(8, x=450)], 2.2).found
    assert s.track_id == 8 and s.generation == 2


def test_overlapping_people_and_multiple_faces_fail_closed():
    s = selector()
    update(s, [face()], [body()], 1)
    assert not update(s, [face()], [body(), body(8, x=220)], 1.1).found
    assert s.last_debug["rejected"] == "people_overlap_ambiguous"
    assert not update(s, [face(), face(260)], [body()], 1.2).found
    assert s.last_debug["rejected"] == "face_body_ambiguous"


def test_face_association_to_two_bodies_is_not_selected():
    s = selector()
    assert not update(s, [face()], [body(), body(8, x=220)], 1).found
    assert s.track_id is None


def test_missing_body_may_follow_face_but_not_face_on_a_different_body():
    s = selector()
    update(s, [face()], [body()], 1)
    assert update(s, [face(255)], [], 1.1).found
    assert not update(s, [face(255)], [body(8)], 1.2).found


def test_nan_and_discontinuous_body_are_rejected():
    s = selector()
    assert not update(s, [face(float("nan"))], [body()], 1).found
    update(s, [face()], [body()], 1.1)
    assert not update(s, [], [body(x=450)], 1.2).found
    assert s.last_debug["rejected"] == "track_discontinuity"


def test_start_without_face_never_chooses_random_body():
    s = selector()
    assert not update(s, [], [body()], 1).found
    assert s.track_id is None


def test_unbound_face_can_bind_when_person_detection_recovers():
    s = selector()
    assert update(s, [face()], [], 1).found
    assert s.track_id is None
    assert update(s, [face()], [body()], 1.1).found
    assert s.track_id == 7 and s.generation == 1


def tracked_box(identity=7, score=.85):
    return SimpleNamespace(id=None if identity is None else [identity], cls=[0.],
                           conf=[score], xyxy=[[200., 100., 300., 400.]])


def test_yolo_wrapper_explicit_botsort_and_skips_boxes_without_id():
    calls = []
    def track(_frame, **options):
        calls.append(options)
        return [SimpleNamespace(boxes=[tracked_box(), tracked_box(None), tracked_box(float("nan"))])]
    detector = YoloPersonTracker({}, model=SimpleNamespace(track=track))
    tracks = detector.track(np.zeros((480, 640, 3), dtype=np.uint8), received_at=1)
    assert [b.track_id for b in tracks] == [7]
    assert calls[0]["persist"] and calls[0]["tracker"].endswith("person-botsort.yaml")
    assert calls[0]["iou"] == .45


def test_stream_gap_resets_botsort_and_unavailable_dependency_fails_closed():
    resets = []
    model = SimpleNamespace(track=lambda *_args, **_kwargs: [],
                            predictor=SimpleNamespace(trackers=[SimpleNamespace(reset=lambda: resets.append(True))]))
    detector = YoloPersonTracker({}, model=model)
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    detector.track(image, received_at=1)
    detector.track(image, received_at=3)
    assert resets == [True]
    detector.available = False
    with pytest.raises(RuntimeError):
        detector.track(image, received_at=3.1)


def test_same_frame_integration_rejects_duplicate_and_stale_before_tracking(monkeypatch):
    monkeypatch.setattr(YoloPersonTracker, "_load_model", lambda self: None)
    tracker = VisionServiceTracker({"vision_service": {"follow_target": "face", "face_detector": "yunet"},
                                    "person_tracking": {"enabled": True}, "face_lock": {"confirm_frames": 1}})
    now = time.time()
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    tracker.reader.latest_packet = lambda: (image, None, 1, now)
    tracker.yunet_face = SimpleNamespace(detect_all=lambda _rgb: [
        (Target(True, 250, 125, 640, 480, .9, "yunet_face", now), {"bbox": [237.5, 110, 25, 30]})])
    calls = []
    def track(frame, *, received_at):
        assert frame is image and received_at == now
        calls.append(True)
        return [body()]
    tracker.yolo_person.track = track
    target, _frame, _error = tracker.read_frame()
    assert target.kind == "face_person_face" and target.ts == now
    assert tracker.read_frame()[0].kind == "vision_frame_duplicate"
    tracker.reader.latest_packet = lambda: (image, None, 2, now-5)
    assert tracker.read_frame()[0].kind == "vision_frame_stale"
    assert calls == [True]


def test_lost_runtime_pauses_and_exposes_selector_state():
    class Adapter:
        continuous_follow = True
        paused = 0
        async def get_state(self):
            return SimpleNamespace(joints_deg=[0.]*6)
        async def pause_follow(self):
            self.paused += 1
        async def send_follow_target(self, *_args):
            pytest.fail("LOST cannot move")
    adapter = Adapter()
    runtime = PersonFollowRuntime(adapter)
    s = selector()
    target = update(s, [], [], time.time())
    runtime.publish(target, debug=s.last_debug)
    assert not asyncio.run(runtime.step()) and adapter.paused == 1
    assert observation_snapshot(runtime)[1]["control_source"] == "LOST"


def test_telemetry_does_not_label_stale_body_as_active():
    runtime = PersonFollowRuntime(None)
    runtime.publish(Target(True, 250, 125, 640, 480, .9, "face_person_body", time.time()-2),
                    debug={"follow_target": "face_person", "control_source": "BODY", "person_track_id": 7})
    state = observation_snapshot(runtime)[1]
    assert state["status"] == "holding" and state["control_source"] == "LOST"
