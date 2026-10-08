import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "vision" / "python"))

from person_follow.camera_view import VirtualPinholeView
from person_follow.detector import Detection, PersonDetector
from person_follow.identity import IdentityManager, IdentityState
from person_follow.pipeline import PersonFollowPipeline
from person_follow.reid import ReIdAdapter
from person_follow.tracker import MultiPersonTracker


def test_virtual_view_requires_calibration_and_produces_provenance():
    view = VirtualPinholeView(width=64, height=48, fx=40, fy=40, cx=32, cy=24, xi=0.8, alpha=0.6)
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    rectified = view.rectify(frame)
    assert rectified.shape == frame.shape
    assert view.camera_view_id.startswith("seucm-pinhole-")
    assert len(view.calibration_hash) == 64


def test_detector_filters_to_person_and_normalizes_backend():
    backend = lambda frame: [
        {"bbox": [1, 2, 20, 30], "score": 0.9, "class_id": 0},
        {"bbox": [5, 6, 10, 12], "score": 0.99, "class_id": 2},
    ]
    detections = PersonDetector(backend, model_id="rtmdet-tiny", model_sha256="abc").detect(np.zeros((10, 10, 3)))
    assert detections == [Detection((1.0, 2.0, 20.0, 30.0), 0.9)]


def test_tracker_and_identity_fail_closed_on_ambiguity_then_reacquire():
    tracker = MultiPersonTracker(iou_threshold=0.2, max_missed=2)
    identities = IdentityManager(reid_threshold=0.8)
    tracks = tracker.update([Detection((0, 0, 20, 40), 0.9)], frame_id="f1")
    state = identities.update(tracks, embeddings={tracks[0].track_id: np.array([1.0, 0.0])})
    assert state.state == IdentityState.LOCKED
    tracks = tracker.update([Detection((1, 0, 21, 40), 0.9), Detection((30, 0, 50, 40), 0.9)], frame_id="f2")
    state = identities.update(tracks, embeddings={t.track_id: np.array([1.0, 0.0]) for t in tracks})
    assert state.state == IdentityState.AMBIGUOUS
    state = identities.update([tracks[0]], embeddings={tracks[0].track_id: np.array([1.0, 0.0])})
    assert state.state == IdentityState.LOCKED


def test_pipeline_emits_complete_observation_with_fake_components():
    view = VirtualPinholeView(width=64, height=48, fx=40, fy=40, cx=32, cy=24, xi=0.8, alpha=0.6)
    detector = PersonDetector(lambda frame: [{"bbox": [10, 5, 30, 45], "score": 0.95, "class_id": 0}], "rtmdet-tiny", "abc")
    reid = ReIdAdapter(lambda frame, tracks: {track.track_id: np.array([1.0, 0.0]) for track in tracks})
    pipeline = PersonFollowPipeline(view, detector, MultiPersonTracker(), IdentityManager(), reid=reid)
    event = pipeline.process(np.zeros((48, 64, 3), dtype=np.uint8), frame_id="f1", captured_at=10.0)
    assert event["frame_id"] == "f1"
    assert event["identity_state"] == "LOCKED"
    assert event["camera_view_id"] == view.camera_view_id
    assert event["model_id"] == "rtmdet-tiny"


def test_reid_without_osnet_backend_fails_closed():
    try:
        ReIdAdapter().embed(np.zeros((10, 10, 3)), [])
    except RuntimeError as error:
        assert str(error) == "MODEL_UNAVAILABLE"
    else:
        raise AssertionError("missing OSNet backend must fail closed")
