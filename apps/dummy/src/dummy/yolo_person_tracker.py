"""BoT-SORT observations from the same latest RGB frame as face detection."""
from dataclasses import dataclass
import importlib.util
import math
import time

from .config import APP_ROOT
from .yolo_person_detector import YoloPersonDetector, _first, _first_row


@dataclass(frozen=True)
class PersonTrack:
    track_id: int
    x: float
    y: float
    w: float
    h: float
    score: float


class YoloPersonTracker(YoloPersonDetector):
    def __init__(self, config, *, model=None):
        super().__init__(config, model=model)
        self.tracker_path = str(APP_ROOT / "configs" / "person-botsort.yaml")
        self.last_frame_at = None
        self.inference_ms = 0.0
        self.detection_iou = float(config.get("person_tracking", {}).get("detection_iou", .45))

    def _load_model(self):
        # Ultralytics otherwise tries to install lap during its first track call.
        if importlib.util.find_spec("lap") is None:
            self.error = "BoT-SORT requires lap>=0.5.12; install requirements-person-tracking.txt first"
            self.available = False
            return
        super()._load_model()

    def track(self, frame, *, received_at):
        if not self.enabled or not self.available:
            raise RuntimeError(self.error or "person tracking unavailable")
        if self.last_frame_at is not None and received_at - self.last_frame_at > 1.0:
            for tracker in getattr(getattr(self.model, "predictor", None), "trackers", []):
                tracker.reset()
        self.last_frame_at = received_at
        started = time.monotonic()
        results = self.model.track(frame, persist=True, tracker=self.tracker_path,
                                   classes=[0], conf=.1, iou=self.detection_iou, verbose=False)
        self.inference_ms = (time.monotonic() - started) * 1000
        tracks = []
        for result in results or []:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                # Unmatched detections have no ID; retained lost predictions are
                # not returned by BoT-SORT's activated current-frame output.
                try:
                    if box.id is None or int(_first(box.cls)) != 0:
                        continue
                    identity = float(_first(box.id))
                    score = float(_first(box.conf))
                    x1, y1, x2, y2 = map(float, _first_row(box.xyxy))
                    if not all(math.isfinite(v) for v in (identity, score, x1, y1, x2, y2)):
                        continue
                    if identity < 0 or not identity.is_integer() or score < self.min_score:
                        continue
                    height, width = frame.shape[:2]
                    x1, x2 = max(0., x1), min(float(width), x2)
                    y1, y2 = max(0., y1), min(float(height), y2)
                    if x2 > x1 and y2 > y1:
                        tracks.append(PersonTrack(int(identity), x1, y1, x2-x1, y2-y1, score))
                except (AttributeError, TypeError, ValueError, IndexError):
                    continue
        return tracks
