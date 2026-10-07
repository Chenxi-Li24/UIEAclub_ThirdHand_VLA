import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.yolo_person_detector import YoloPersonDetector


class FakeBox:
    def __init__(self, xyxy, cls, conf):
        self.xyxy = np.asarray([xyxy], dtype=float)
        self.cls = np.asarray([cls], dtype=float)
        self.conf = np.asarray([conf], dtype=float)


class FakeResult:
    def __init__(self):
        self.boxes = [
            FakeBox([10, 20, 50, 80], 0, 0.40),
            FakeBox([100, 120, 220, 360], 0, 0.92),
            FakeBox([300, 20, 360, 90], 39, 0.99),
        ]


class FakeModel:
    def __call__(self, frame, verbose=False, classes=None, conf=0.25):
        assert classes == [0]
        assert conf == 0.25
        return [FakeResult()]


def test_yolo_person_detector_returns_person_candidates_sorted_by_score():
    detector = YoloPersonDetector({"vision_service": {"yolo_person_min_score": 0.25}}, model=FakeModel())

    candidates = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))

    assert len(candidates) == 2
    assert candidates[0].kind == "yolo_person"
    assert candidates[0].score == 0.92
    assert candidates[0].u == 160
    assert candidates[0].v == 240
    assert candidates[0].w == 120
    assert candidates[0].h == 240


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("YOLO_PERSON_DETECTOR_OK")
