"""OpenCV YuNet detector using explicitly prepared, local model weights."""
from pathlib import Path
import time

import cv2
import numpy as np

from .config import resolve_project_path
from .tracker import Target


class YuNetFaceDetector:
    def __init__(self, model_path, *, min_confidence=0.8):
        self.model_path = str(resolve_project_path(model_path))
        self.min_confidence = float(min_confidence)
        self.detector = None
        self.error = None

    @property
    def available(self):
        return self.detector is not None

    def open(self):
        if self.available:
            return True
        try:
            if not Path(self.model_path).is_file():
                raise FileNotFoundError(f"YuNet model not found: {self.model_path}; run prepare_face_model.py")
            self.detector = cv2.FaceDetectorYN.create(self.model_path, "", (640, 480),
                                                     self.min_confidence, .3, 5000)
            self.error = None
            return True
        except Exception as exc:
            self.error = str(exc)
            return False

    def close(self):
        self.detector = None

    def detect_all(self, rgb_frame):
        if not self.open():
            raise RuntimeError(self.error)
        h, w = rgb_frame.shape[:2]
        self.detector.setInputSize((w, h))
        _count, faces = self.detector.detect(cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR))
        converted = []
        for row in [] if faces is None else faces:
            if len(row) < 15 or not np.isfinite(row).all() or float(row[14]) < self.min_confidence:
                continue
            x, y, bw, bh = [float(v) for v in row[:4]]
            x0, y0 = max(0., x), max(0., y)
            x1, y1 = min(float(w), x + bw), min(float(h), y + bh)
            if x1 <= x0 or y1 <= y0:
                continue
            target = Target(True, (x0 + x1) / 2, (y0 + y1) / 2, w, h,
                            float(row[14]), "yunet_face", time.time())
            debug = {"bbox": [x0, y0, x1 - x0, y1 - y0],
                     "landmarks": [[float(row[i]), float(row[i + 1])] for i in range(4, 14, 2)]}
            converted.append((target, debug))
        return converted
