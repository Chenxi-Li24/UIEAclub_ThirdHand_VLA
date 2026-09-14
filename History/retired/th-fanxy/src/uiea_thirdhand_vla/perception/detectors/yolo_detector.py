"""
YOLO-based object detector using Ultralytics.
Outputs Detection objects compatible with ArUco detector format.
"""

import cv2
import numpy as np

from ...utils.types import Detection
from .base import BaseDetector


class YoloDetector(BaseDetector):
    """YOLO object detection for markerless picking."""

    def __init__(self, model_path="yolov8n.pt", confidence=0.5, transforms=None):
        self.model_path = model_path
        self.confidence = confidence
        self.transforms = transforms  # CoordinateTransforms instance
        self._model = None
        self._class_names = {}

    def _load_model(self):
        """Lazy-load YOLO model."""
        if self._model is not None:
            return
        try:
            from ultralytics import YOLO
            self._model = YOLO(self.model_path)
            self._class_names = self._model.names
            print(f"[YOLO] Loaded {self.model_path}, {len(self._class_names)} classes")
        except ImportError:
            print("[YOLO] ultralytics not installed. Run: pip install ultralytics")
            raise
        except Exception as e:
            print(f"[YOLO] Failed to load model: {e}")
            raise

    def detect(self, image: np.ndarray) -> list[Detection]:
        """Run YOLO inference and return Detection list."""
        if image is None:
            return []

        self._load_model()
        assert self._model is not None
        results = self._model(image, conf=self.confidence, verbose=False)

        detections = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for box in boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                xyxy = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = xyxy

                cx = int((x1 + x2) / 2)
                cy = int((y1 + y2) / 2)
                label = self._class_names.get(cls_id, f"class_{cls_id}")

                # Corners in 2D (clockwise from top-left)
                corners = [
                    (float(x1), float(y1)),
                    (float(x2), float(y1)),
                    (float(x2), float(y2)),
                    (float(x1), float(y2)),
                ]

                detections.append(Detection(
                    id=cls_id,
                    label=label,
                    confidence=conf,
                    corners_2d=corners,
                    center_pixel=(cx, cy),
                    pose_camera=None,  # YOLO alone can't estimate 3D pose
                    pose_base=None,
                ))

        return detections

    def draw(self, image: np.ndarray, detections: list[Detection]) -> np.ndarray:
        """Draw bounding boxes and labels."""
        out = image.copy()
        for det in detections:
            if not det.corners_2d:
                continue
            x1 = int(det.corners_2d[0][0])
            y1 = int(det.corners_2d[0][1])
            x2 = int(det.corners_2d[2][0])
            y2 = int(det.corners_2d[2][1])

            # Color by confidence
            color = (0, int(255 * det.confidence), int(255 * (1 - det.confidence)))

            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            cv2.putText(out, f"{det.label} {det.confidence:.2f}",
                        (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            cv2.circle(out, det.center_pixel, 3, color, -1)

        return out

    def set_camera_matrix(self, K: np.ndarray, dist: np.ndarray = None):
        self.K = K
        self.dist = dist if dist is not None else np.zeros(4)
