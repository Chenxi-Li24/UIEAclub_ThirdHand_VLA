import asyncio
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.config import load_config
from dummy.face_lock_tracker import FaceLockTracker
from dummy.mediapipe_face import targets_from_mediapipe_result
from dummy.person_follow.runtime import PersonFollowRuntime
from dummy.person_follow.telemetry import observation_snapshot
from dummy.person_lock_tracker import Candidate
from dummy.tracker import Target
from dummy.vision_service_tracker import VisionServiceTracker


def face(u=220, v=180, score=0.9, kind="mediapipe_face"):
    return Candidate(u, v, 80, 90, score, kind)


def lock(config=None):
    return FaceLockTracker(config or {"face_lock": {"confirm_frames": 1, "auto_reacquire": False}})


def update(tracker, candidates, now):
    return tracker.update(candidates, now=now, frame_size=(640, 480))


def test_start_requires_two_distinct_face_observations():
    tracker = FaceLockTracker({})
    assert not update(tracker, [face()], 1).found
    assert update(tracker, [face(225)], 1.1).kind == "face_lock"


def test_faces_only_and_nonfinite_detection_is_rejected():
    tracker = lock()
    assert not update(tracker, [face(kind="person"), face(u=float("nan"))], 1).found
    assert tracker.state == "waiting_for_first_face"


def test_existing_face_is_not_replaced_by_bigger_higher_score_face():
    tracker = lock()
    update(tracker, [face()], 1)
    result = update(tracker, [face(225, score=.5), Candidate(500, 180, 160, 180, .99, "face")], 1.1)
    assert result.kind == "face_lock" and result.u < 230
    assert tracker.previous.u == 225


def test_far_other_face_never_relocks_even_when_sustained():
    tracker = lock()
    update(tracker, [face()], 1)
    for now in (1.1, 1.5, 1.9):
        assert update(tracker, [face(500)], now).kind == "face_lock_hold"
    result = update(tracker, [face(500)], 2.1)
    assert not result.found and result.kind == "face_waiting_for_ok"


def test_loss_latches_even_when_original_face_reappears():
    tracker = lock()
    update(tracker, [face()], 1)
    assert update(tracker, [], 1.1).kind == "face_lock_hold"
    assert not update(tracker, [], 2.1).found
    assert not update(tracker, [face()], 2.2).found
    assert tracker.state == "waiting_for_ok"


def test_first_fresh_frame_after_stream_gap_cannot_reacquire():
    tracker = lock()
    update(tracker, [face()], 1)
    assert not update(tracker, [face()], 3).found
    assert tracker.state == "waiting_for_ok"


def test_short_missed_detection_holds_then_resumes_near_face():
    tracker = lock()
    update(tracker, [face()], 1)
    held = update(tracker, [], 1.2)
    assert held.kind == "face_lock_hold" and held.ts == 1
    assert update(tracker, [face(225)], 1.3).kind == "face_lock"


def test_crossing_ambiguous_faces_pause_instead_of_switching():
    tracker = lock()
    update(tracker, [face()], 1)
    held = update(tracker, [face(215), face(225)], 1.1)
    assert held.kind == "face_lock_hold"
    assert tracker.last_debug["rejected"] == "face_association_ambiguous"


def test_mediapipe_conversion_returns_all_faces_not_only_best():
    def detection(x):
        return SimpleNamespace(bounding_box=SimpleNamespace(origin_x=x, origin_y=10, width=40, height=50),
                               categories=[SimpleNamespace(score=.9)])
    result = SimpleNamespace(detections=[detection(10), detection(100)])
    faces = targets_from_mediapipe_result(result, 640, 480)
    assert [target.u for target, _debug in faces] == [30, 120]


def test_face_mode_never_calls_body_motion_or_depth_detectors(monkeypatch):
    tracker = VisionServiceTracker({"vision_service": {"follow_target": "face", "rgbd_enabled": True},
                                    "face_lock": {"confirm_frames": 1}})
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    timestamp = time.time() - .1
    tracker.reader.latest_packet = lambda: (image, None, 1, timestamp)
    tracker.mediapipe_face = SimpleNamespace(detect_all=lambda _rgb: [
        (Target(True, 220, 180, 640, 480, .9, "mediapipe_face", timestamp), {"bbox": [180, 135, 80, 90]})])
    def forbidden(*_args):
        raise AssertionError("face-only mode must not select body/motion/depth")
    monkeypatch.setattr(tracker.yolo_person, "detect", forbidden)
    monkeypatch.setattr(tracker, "detect", forbidden)
    monkeypatch.setattr(tracker, "_merge_rgbd_target", forbidden)
    target, _frame, _error = tracker.read_frame()
    assert target.kind == "face_lock" and target.ts == timestamp
    assert tracker.last_debug["face_count"] == 1
    assert tracker.last_debug["lock_candidate"]["kind"] == "mediapipe_face"
    assert tracker.read_frame()[0].kind == "vision_frame_duplicate"
    assert tracker.yolo_person.enabled is False


def test_face_mode_has_no_health_fallback_without_camera(monkeypatch):
    tracker = VisionServiceTracker({"vision_service": {"follow_target": "face", "allow_health_fallback": True}})
    tracker.reader.latest_packet = lambda: (None, "offline", 1, 0)
    monkeypatch.setattr(tracker, "_read_health_target", lambda: pytest.fail("no body health fallback"))
    assert not tracker.read_frame()[0].found


def test_face_mode_missing_face_detector_fails_closed():
    tracker = VisionServiceTracker({"vision_service": {"follow_target": "face", "mediapipe_face_enabled": False}})
    with pytest.raises(RuntimeError, match="requires MediaPipe"):
        tracker._read_face_target(np.zeros((48, 64, 3), dtype=np.uint8), time.time())


def test_loss_pauses_continuous_follow_and_telemetry_reports_waiting():
    class Adapter:
        continuous_follow = True
        paused = 0
        async def get_state(self):
            return SimpleNamespace(joints_deg=[0.] * 6)
        async def pause_follow(self):
            self.paused += 1
        async def send_follow_target(self, *_args):
            pytest.fail("lost face must not send a joint target")
    adapter = Adapter()
    runtime = PersonFollowRuntime(adapter)
    runtime.publish(Target(False, kind="face_waiting_for_ok", ts=time.time()),
                    debug={"follow_target": "face", "lock_state": "waiting_for_ok", "face_count": 2})
    assert not asyncio.run(runtime.step())
    assert adapter.paused == 1
    state = observation_snapshot(runtime)[1]
    assert state["lock_state"] == "waiting_for_ok" and state["follow_target"] == "face"


def test_shipped_config_uses_face_only_and_disables_wave_and_body():
    config = load_config()
    assert config["vision_service"]["follow_target"] == "face"
    assert config["vision_service"]["yolo_person_enabled"] is False
    assert config["vision_service"]["wave_lock_enabled"] is False
    assert config["vision_service"]["face_detector"] == "yunet"
    assert config["face_lock"]["auto_reacquire"] is True


def test_auto_reacquire_confirms_a_new_face_after_loss():
    tracker = lock({"face_lock": {"confirm_frames": 2, "auto_reacquire": True}})
    update(tracker, [face()], 1)
    update(tracker, [face()], 1.1)
    assert tracker.selection_generation == 1
    assert update(tracker, [], 1.2).kind == "face_lock_hold"
    assert not update(tracker, [face(500)], 2.2).found
    assert tracker.state == "confirming_face"
    reacquired = update(tracker, [face(501)], 2.3)
    assert reacquired.kind == "face_lock" and reacquired.u == 501
    assert tracker.selection_generation == 2


def test_auto_reacquire_waits_without_faces_and_does_not_switch_early():
    tracker = lock({"face_lock": {"confirm_frames": 1, "auto_reacquire": True}})
    update(tracker, [face()], 1)
    assert update(tracker, [face(500)], 1.2).kind == "face_lock_hold"
    assert not update(tracker, [], 2.2).found
    assert tracker.state == "reacquiring_face"
    assert update(tracker, [face(500)], 2.3).kind == "face_lock"


def test_yunet_face_only_path_uses_yunet_confidence_and_candidate_kind(monkeypatch):
    tracker = VisionServiceTracker({"vision_service": {"follow_target": "face", "face_detector": "yunet"},
                                    "face_lock": {"confirm_frames": 1}})
    tracker.yunet_face = SimpleNamespace(detect_all=lambda _rgb: [
        (Target(True, 220, 180, 640, 480, .9, "yunet_face", time.time()), {"bbox": [200, 155, 40, 50]}),
        (Target(True, 420, 180, 640, 480, .3, "yunet_face", time.time()), {"bbox": [400, 155, 40, 50]})])
    target = tracker._read_face_target(np.zeros((480, 640, 3), dtype=np.uint8), time.time())
    assert target.kind == "face_lock"
    assert tracker.last_debug["face_detector"] == "yunet"
    assert tracker.last_debug["face_count"] == 1
    assert tracker.last_debug["lock_candidate"]["kind"] == "yunet_face"
