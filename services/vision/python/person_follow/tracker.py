from __future__ import annotations

from dataclasses import dataclass

from .detector import Detection


def _iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return overlap / max(area_a + area_b - overlap, 1e-9)


@dataclass(frozen=True)
class Track:
    track_id: int
    bbox_xyxy: tuple[float, float, float, float]
    score: float
    frame_id: str


class MultiPersonTracker:
    """Small deterministic adapter; a BoT-SORT backend can replace matching without changing contracts."""
    def __init__(self, iou_threshold=0.3, max_missed=10):
        self.iou_threshold = float(iou_threshold)
        self.max_missed = int(max_missed)
        self._next_id = 1
        self._boxes = {}

    def update(self, detections: list[Detection], frame_id: str):
        available = set(self._boxes)
        tracks = []
        for detection in sorted(detections, key=lambda d: d.score, reverse=True):
            matches = [(track_id, _iou(detection.bbox_xyxy, self._boxes[track_id])) for track_id in available]
            track_id, score = max(matches, key=lambda pair: pair[1], default=(None, -1.0))
            if track_id is None or score < self.iou_threshold:
                track_id = self._next_id
                self._next_id += 1
            else:
                available.remove(track_id)
            self._boxes[track_id] = detection.bbox_xyxy
            tracks.append(Track(track_id, detection.bbox_xyxy, detection.score, frame_id))
        return tracks
