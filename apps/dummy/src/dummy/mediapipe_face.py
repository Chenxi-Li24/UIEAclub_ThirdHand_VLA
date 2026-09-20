from __future__ import annotations

import time
from pathlib import Path

from .tracker import Target


def _score_of(detection) -> float:
    categories = getattr(detection, "categories", None) or []
    if not categories:
        return 0.0
    return float(getattr(categories[0], "score", 0.0) or 0.0)


def target_from_mediapipe_detection(detection, frame_w: int, frame_h: int):
    """Convert a MediaPipe face detection into Dummy's common Target shape."""
    bbox = getattr(detection, "bounding_box", None)
    if bbox is None:
        return Target(False, w=frame_w, h=frame_h, kind="mediapipe_face_missing_bbox", ts=time.time()), {}
    x = int(getattr(bbox, "origin_x", 0) or 0)
    y = int(getattr(bbox, "origin_y", 0) or 0)
    w = int(getattr(bbox, "width", 0) or 0)
    h = int(getattr(bbox, "height", 0) or 0)
    if w <= 0 or h <= 0:
        return Target(False, w=frame_w, h=frame_h, kind="mediapipe_face_empty_bbox", ts=time.time()), {
            "bbox": (x, y, w, h),
        }
    u = float(x + w / 2)
    v = float(y + h / 2)
    score = _score_of(detection)
    debug = {
        "bbox": (x, y, w, h),
        "person_bbox": (x, y, w, h),
        "raw_target": (u, v),
        "contours": [],
    }
    return Target(True, u, v, frame_w, frame_h, score, "mediapipe_face", time.time()), debug


def target_from_mediapipe_result(result, frame_w: int, frame_h: int, *, reference=None):
    detections = list(getattr(result, "detections", None) or [])
    if not detections:
        return Target(False, w=frame_w, h=frame_h, kind="mediapipe_face_none", ts=time.time()), {}
    if reference is None:
        best = max(detections, key=_score_of)
    else:
        ref_u, ref_v = [float(value) for value in reference]

        def distance_squared(detection):
            bbox = getattr(detection, "bounding_box", None)
            if bbox is None:
                return float("inf")
            u = float(getattr(bbox, "origin_x", 0) or 0) + float(getattr(bbox, "width", 0) or 0) / 2
            v = float(getattr(bbox, "origin_y", 0) or 0) + float(getattr(bbox, "height", 0) or 0) / 2
            return (u - ref_u) ** 2 + (v - ref_v) ** 2

        best = min(detections, key=distance_squared)
    return target_from_mediapipe_detection(best, frame_w, frame_h)


def remap_debug_from_crop(debug: dict, x0: int, y0: int) -> dict:
    out = dict(debug or {})
    bbox = out.get("bbox")
    if bbox:
        x, y, w, h = bbox
        out["bbox"] = (int(x + x0), int(y + y0), int(w), int(h))
        out["person_bbox"] = out["bbox"]
    raw = out.get("raw_target")
    if raw:
        out["raw_target"] = (float(raw[0] + x0), float(raw[1] + y0))
    return out


class MediaPipeFaceDetector:
    """Small optional wrapper around Google MediaPipe Face Detector Tasks."""

    def __init__(self, model_path: str, *, min_confidence: float = 0.5):
        self.model_path = str(model_path)
        self.min_confidence = float(min_confidence)
        self.detector = None
        self.error = None

    @property
    def available(self) -> bool:
        return self.detector is not None

    def open(self) -> bool:
        if self.detector is not None:
            return True
        path = Path(self.model_path)
        if not path.exists():
            self.error = f"MediaPipe model not found: {path}"
            return False
        try:
            import mediapipe as mp

            options = mp.tasks.vision.FaceDetectorOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),
                running_mode=mp.tasks.vision.RunningMode.IMAGE,
                min_detection_confidence=self.min_confidence,
            )
            self.detector = mp.tasks.vision.FaceDetector.create_from_options(options)
            self.error = None
            return True
        except Exception as exc:
            self.detector = None
            self.error = str(exc)
            return False

    def close(self):
        if self.detector is not None:
            try:
                self.detector.close()
            finally:
                self.detector = None

    def detect(self, rgb_frame, *, reference=None):
        if self.detector is None and not self.open():
            h, w = rgb_frame.shape[:2]
            return Target(False, w=w, h=h, kind="mediapipe_unavailable", ts=time.time()), {}
        import mediapipe as mp

        h, w = rgb_frame.shape[:2]
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        result = self.detector.detect(image)
        return target_from_mediapipe_result(result, w, h, reference=reference)

    def detect_crop(self, rgb_frame, crop, *, reference=None):
        x0, y0, x1, y1 = [int(v) for v in crop]
        x0 = max(0, min(x0, rgb_frame.shape[1] - 1))
        x1 = max(x0 + 1, min(x1, rgb_frame.shape[1]))
        y0 = max(0, min(y0, rgb_frame.shape[0] - 1))
        y1 = max(y0 + 1, min(y1, rgb_frame.shape[0]))
        crop_reference = None
        if reference is not None:
            crop_reference = (float(reference[0]) - x0, float(reference[1]) - y0)
        target, debug = self.detect(
            rgb_frame[y0:y1, x0:x1],
            reference=crop_reference,
        )
        if not target.found:
            return target, remap_debug_from_crop(debug, x0, y0)
        target.u += x0
        target.v += y0
        target.w = rgb_frame.shape[1]
        target.h = rgb_frame.shape[0]
        return target, remap_debug_from_crop(debug, x0, y0)
