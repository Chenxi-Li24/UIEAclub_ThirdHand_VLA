"""
Camera interface — Lumos Ego STD via V4L2.
Provides RGB capture and SEUCM intrinsics access.
"""

import threading
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from .calibration import CameraCalibration


class Camera:
    """V4L2 wrapper for Lumos Ego STD 1280×1280 RGB camera."""

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.device = cfg.get("device", 0)
        self.width = cfg.get("width", 1280)
        self.height = cfg.get("height", 1280)
        self.fps = cfg.get("fps", 100)
        self._cap: cv2.VideoCapture | None = None
        self._is_open = False
        self._latest_frame: np.ndarray | None = None
        self._lock = threading.Lock()

        # SEUCM intrinsics (loaded from device or config)
        self.K = np.array([
            [392.168, 0, 637.761],
            [0, 392.168, 640.597],
            [0, 0, 1]
        ], dtype=np.float64)
        self.seucm_params = {
            "alpha": 0.678979,
            "beta": 0.749026,
            "eu": 636.665,
            "ev": 639.882,
        }

    # ---- Lifecycle ----

    def open(self) -> bool:
        """Open camera device and start background capture."""
        if self._is_open:
            return True

        self._cap = cv2.VideoCapture(self.device)
        if not self._cap.isOpened():
            return False

        # YU12 raw capture to avoid extra conversion
        self._cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YU12'))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap.set(cv2.CAP_PROP_FPS, self.fps)

        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._is_open = True

        # Background capture thread
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        print(f"[Camera] Opened {actual_w}×{actual_h} on /dev/video{self.device}")
        return True

    def _capture_loop(self):
        """Continuous capture in background thread."""
        while self._running and self._cap is not None:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.001)
                continue
            try:
                bgr = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
                with self._lock:
                    self._latest_frame = bgr
            except Exception:
                pass

    def capture(self) -> np.ndarray | None:
        """Return the latest RGB frame (BGR format, 1280×1280). Non-blocking."""
        if not self._is_open:
            raise RuntimeError("Camera not opened")
        with self._lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def capture_blocking(self, timeout: float = 2.0) -> np.ndarray:
        """Wait for a fresh frame. Blocks until frame available or timeout."""
        start = time.time()
        while time.time() - start < timeout:
            frame = self.capture()
            if frame is not None:
                return frame
            time.sleep(0.01)
        raise TimeoutError(f"No frame received within {timeout}s")

    def close(self):
        """Release camera resources."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            self._cap.release()
        self._is_open = False
        print("[Camera] Closed")

    @property
    def is_open(self) -> bool:
        return self._is_open

    # ---- Intrinsics ----

    def set_intrinsics(self, calib: "CameraCalibration"):
        """Load intrinsics from CameraCalibration object."""
        self.K = calib.K
        if calib.model == "seucm":
            self.seucm_params = calib.seucm_params

    def get_camera_matrix(self) -> np.ndarray:
        return self.K.copy()

    def get_dist_coeffs(self) -> np.ndarray:
        """SEUCM camera has no traditional distortion coefficients; return zeros."""
        return np.zeros(4)

    # ---- Helpers ----

    def snapshot(self, path: str) -> bool:
        """Save current frame to disk."""
        frame = self.capture()
        if frame is None:
            return False
        return cv2.imwrite(path, frame)
