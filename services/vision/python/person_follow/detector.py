from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Detection:
    bbox_xyxy: tuple[float, float, float, float]
    score: float


class PersonDetector:
    def __init__(self, backend, model_id: str, model_sha256: str, score_threshold=0.3, person_class_id=0):
        if backend is None:
            raise RuntimeError("MODEL_UNAVAILABLE")
        self.backend = backend
        self.model_id = model_id
        self.model_sha256 = model_sha256
        self.score_threshold = float(score_threshold)
        self.person_class_id = int(person_class_id)

    def detect(self, frame):
        result = []
        for item in self.backend(frame):
            if int(item.get("class_id", -1)) != self.person_class_id or float(item.get("score", 0)) < self.score_threshold:
                continue
            box = tuple(float(v) for v in item["bbox"])
            score = float(item["score"])
            if len(box) != 4 or not all(isfinite(v) for v in box) or box[2] <= box[0] or box[3] <= box[1]:
                continue
            result.append(Detection(box, score))
        return result
