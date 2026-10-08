from __future__ import annotations

import time

from .reid import ReIdAdapter


class PersonFollowPipeline:
    def __init__(self, view, detector, tracker, identities, reid=None):
        self.view = view
        self.detector = detector
        self.tracker = tracker
        self.identities = identities
        self.reid = reid or ReIdAdapter()

    def process(self, frame, *, frame_id: str, captured_at: float):
        started = time.perf_counter()
        rectified = self.view.rectify(frame)
        tracks = self.tracker.update(self.detector.detect(rectified), frame_id)
        embeddings = self.reid.embed(rectified, tracks)
        identity = self.identities.update(tracks, embeddings)
        track = next((item for item in tracks if item.track_id == identity.track_id), None)
        if track is None:
            box, center, confidence = None, None, 0.0
        else:
            box = track.bbox_xyxy
            center = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
            confidence = track.score
        return {
            "schema_version": "1.0", "frame_id": frame_id, "captured_at": float(captured_at),
            "camera_view_id": self.view.camera_view_id, "calibration_hash": self.view.calibration_hash,
            "model_id": self.detector.model_id, "model_sha256": self.detector.model_sha256,
            "identity_id": identity.identity_id, "identity_state": identity.state.value,
            "track_id": identity.track_id, "bbox_xyxy": box, "center_px": center,
            "confidence": confidence, "latency_ms": (time.perf_counter() - started) * 1000.0,
        }
