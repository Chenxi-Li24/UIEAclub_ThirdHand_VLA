from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from .filters import OneEuro


@dataclass
class Target:
    found: bool
    u: float = 0.0
    v: float = 0.0
    w: int = 0
    h: int = 0
    score: float = 0.0
    kind: str = "none"
    ts: float = 0.0


class HumanTracker:
    def __init__(self, config):
        c = config.get("vision", {})
        self.index = int(c.get("camera_index", 0))
        self.width = int(c.get("frame_w", 640))
        self.height = int(c.get("frame_h", 480))
        self.fourcc = str(c.get("fourcc", "") or "").upper()
        self.mirror = bool(c.get("mirror", False))
        hz = float(c.get("hz", 15))
        self.fx = OneEuro(hz, c.get("filter_min_cutoff", 1.0), c.get("filter_beta", 0.03))
        self.fy = OneEuro(hz, c.get("filter_min_cutoff", 1.0), c.get("filter_beta", 0.03))
        self.cap = None
        self.bg = None
        self.last_debug = {}
        self.face = None
        if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data"):
            cascade = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.face = cv2.CascadeClassifier(cascade)

    def open(self):
        if self.cap is None:
            self.cap = cv2.VideoCapture(self.index)
            if self.fourcc:
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc[:4]))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        return self.cap.isOpened()

    def close(self):
        if self.cap:
            self.cap.release()
            self.cap = None

    def read(self):
        if not self.open():
            return Target(False, ts=time.time())
        ok, frame = self.cap.read()
        if not ok:
            return Target(False, ts=time.time())
        if frame is not None and len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        if self.mirror:
            frame = cv2.flip(frame, 1)
        return self.read_frame(frame)

    def read_frame(self, frame):
        h, w = frame.shape[:2]
        gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face.detectMultiScale(gray, 1.1, 5, minSize=(40, 40)) if self.face is not None and not self.face.empty() else []
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
            self.last_debug = {
                "gray": gray,
                "mask": np.zeros_like(gray),
                "bbox": (int(x), int(y), int(fw), int(fh)),
                "contours": [],
            }
            return Target(True, self.fx(x + fw / 2), self.fy(y + fh / 2), w, h, float(fw * fh) / (w * h), "face", time.time())
        blur = cv2.GaussianBlur(gray, (21, 21), 0)
        if self.bg is None:
            self.bg = blur.astype("float")
            self.last_debug = {
                "gray": gray,
                "mask": np.zeros_like(gray),
                "bbox": None,
                "contours": [],
            }
            return Target(False, w=w, h=h, ts=time.time())
        cv2.accumulateWeighted(blur, self.bg, 0.04)
        diff = cv2.absdiff(blur, cv2.convertScaleAbs(self.bg))
        _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        th = cv2.dilate(th, None, iterations=2)
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [c for c in contours if cv2.contourArea(c) > 1200]
        if not contours:
            self.fx.reset()
            self.fy.reset()
            self.last_debug = {
                "gray": gray,
                "mask": th,
                "bbox": None,
                "contours": contours,
            }
            return Target(False, w=w, h=h, ts=time.time())
        c = max(contours, key=cv2.contourArea)
        x, y, fw, fh = cv2.boundingRect(c)
        self.last_debug = {
            "gray": gray,
            "mask": th,
            "bbox": (int(x), int(y), int(fw), int(fh)),
            "contours": contours,
        }
        return Target(True, self.fx(x + fw / 2), self.fy(y + fh / 2), w, h, float(cv2.contourArea(c)) / (w * h), "motion", time.time())
