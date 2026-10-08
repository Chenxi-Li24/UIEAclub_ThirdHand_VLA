from __future__ import annotations

from pathlib import Path

from .person_lock_tracker import Candidate
from .config import PROJECT_ROOT


class YoloPersonDetector:
    def __init__(self, config, *, model=None):
        vision = config.get("vision_service", {})
        self.enabled = bool(vision.get("yolo_person_enabled", True))
        self.model_path = str(vision.get("yolo_person_model_path", PROJECT_ROOT / "local/models/vision/yolov8n.pt"))
        self.min_score = float(vision.get("yolo_person_min_score", 0.25))
        self.model = model
        self.available = model is not None
        self.error = None
        if self.enabled and self.model is None:
            self._load_model()

    def _load_model(self):
        try:
            from ultralytics import YOLO

            path = Path(self.model_path)
            self.model = YOLO(str(path if path.exists() else self.model_path))
            self.available = True
        except Exception as exc:
            self.error = str(exc)
            self.available = False

    def detect(self, frame):
        if not self.enabled or not self.available or self.model is None:
            return []
        try:
            results = self.model(frame, verbose=False, classes=[0], conf=self.min_score)
        except Exception as exc:
            self.error = str(exc)
            return []

        candidates = []
        for result in results or []:
            for box in getattr(result, "boxes", []) or []:
                parsed = self._parse_box(box)
                if parsed is not None:
                    candidates.append(parsed)
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates

    def _parse_box(self, box):
        try:
            cls = int(float(_first(box.cls)))
            score = float(_first(box.conf))
            if cls != 0 or score < self.min_score:
                return None
            x1, y1, x2, y2 = [float(value) for value in _first_row(box.xyxy)]
            width = max(1.0, x2 - x1)
            height = max(1.0, y2 - y1)
            return Candidate(
                x1 + width / 2.0,
                y1 + height / 2.0,
                width,
                height,
                score,
                "yolo_person",
            )
        except Exception:
            return None


def _first(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return value[0]


def _first_row(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return value[0]
