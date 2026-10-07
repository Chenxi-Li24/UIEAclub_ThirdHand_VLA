import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.person_lock_tracker import Candidate, PersonLockTracker


def test_lock_tracker_smooths_small_target_motion():
    tracker = PersonLockTracker({"person_lock": {"relock_frames": 2}})

    first = tracker.update([Candidate(100, 100, 80, 80, 0.9, "face")], now=1.0, frame_size=(640, 480))
    second = tracker.update([Candidate(112, 104, 80, 80, 0.9, "face")], now=1.1, frame_size=(640, 480))

    assert first.found
    assert second.found
    assert second.kind == "person_lock"
    assert 100 < second.u < 112


def test_lock_tracker_holds_short_occlusion_without_switching_target():
    tracker = PersonLockTracker({"person_lock": {"hold_s": 1.0}})
    tracker.update([Candidate(220, 200, 90, 90, 0.9, "face")], now=1.0, frame_size=(640, 480))

    held = tracker.update([], now=1.4, frame_size=(640, 480))

    assert held.found
    assert held.kind == "person_lock_hold"
    assert held.u == 220
    assert held.v == 200


def test_lock_tracker_does_not_jump_to_far_single_frame_candidate():
    tracker = PersonLockTracker({"person_lock": {"relock_frames": 3, "jump_px": 120}})
    tracker.update([Candidate(220, 200, 90, 90, 0.9, "face")], now=1.0, frame_size=(640, 480))

    held = tracker.update([Candidate(500, 300, 90, 90, 0.95, "face")], now=1.1, frame_size=(640, 480))

    assert held.kind == "person_lock_hold"
    assert held.u == 220


def test_lock_tracker_relocks_after_sustained_far_candidate():
    tracker = PersonLockTracker({"person_lock": {"relock_frames": 2, "jump_px": 120}})
    tracker.update([Candidate(220, 200, 90, 90, 0.9, "face")], now=1.0, frame_size=(640, 480))

    tracker.update([Candidate(500, 300, 90, 90, 0.95, "face")], now=1.1, frame_size=(640, 480))
    relocked = tracker.update([Candidate(506, 302, 90, 90, 0.95, "face")], now=1.2, frame_size=(640, 480))

    assert relocked.kind == "person_lock"
    assert relocked.u > 300


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("PERSON_LOCK_TRACKER_OK")
