from __future__ import annotations

import threading
import time
import urllib.request
import json
from pathlib import Path
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

from .filters import OneEuro
from .mediapipe_face import MediaPipeFaceDetector
from .tracker import Target


class MjpegReader:
    def __init__(self, url):
        self.url = url
        self.lock = threading.Lock()
        self.frame = None
        self.error = None
        self.sequence = 0
        self.received_at = 0.0
        self.stop = False
        self.thread = None

    def start(self):
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def close(self):
        self.stop = True

    def _run(self):
        while not self.stop:
            try:
                with urllib.request.urlopen(self.url, timeout=5) as response:
                    buf = b""
                    while not self.stop:
                        chunk = response.read(8192)
                        if not chunk:
                            raise EOFError("stream ended")
                        buf += chunk
                        start = buf.find(b"\xff\xd8")
                        end = buf.find(b"\xff\xd9", start + 2)
                        if start >= 0 and end >= 0:
                            jpg = buf[start:end + 2]
                            buf = buf[end + 2:]
                            rgb = np.asarray(Image.open(BytesIO(jpg)).convert("RGB"))
                            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                            with self.lock:
                                self.frame = bgr
                                self.error = None
                                self.sequence += 1
                                self.received_at = time.time()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                time.sleep(1)

    def latest(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy(), self.error

    def latest_packet(self):
        """Return frame data plus freshness metadata for control consumers."""

        with self.lock:
            frame = None if self.frame is None else self.frame.copy()
            return frame, self.error, self.sequence, self.received_at


class VisionServiceTracker:
    def __init__(self, config):
        v = config.get("vision_service", {})
        self.url = v.get("mjpeg_url", "http://127.0.0.1:3100/camera/xvisio/vision")
        self.health_url = v.get("health_url", "http://127.0.0.1:3100/health")
        self.allow_health_fallback = bool(v.get("allow_health_fallback", False))
        self.prefer_labels = tuple(v.get("prefer_labels", ["person", "face", "human", "bottle"]))
        self.width = int(config.get("vision", {}).get("frame_w", v.get("frame_w", 640)))
        self.height = int(config.get("vision", {}).get("frame_h", v.get("frame_h", 480)))
        self.min_area = float(v.get("min_motion_area", 1600))
        self.target_hold_s = float(v.get("target_hold_s", 2.5))
        self.max_frame_age_s = float(v.get("max_frame_age_s", 0.5))
        self.motion_requires_face_lock = bool(v.get("motion_requires_face_lock", True))
        self.motion_lock_radius_px = float(v.get("motion_lock_radius_px", 170))
        self.wave_lock_enabled = bool(v.get("wave_lock_enabled", True))
        self.wave_lock_frames = int(v.get("wave_lock_frames", 4))
        self.wave_lock_min_score = float(v.get("wave_lock_min_score", 0.018))
        self.wave_lock_center_radius_px = float(v.get("wave_lock_center_radius_px", 230))
        self.face_scale_factor = float(v.get("face_scale_factor", 1.05))
        self.face_min_neighbors = int(v.get("face_min_neighbors", 3))
        self.face_min_size_px = int(v.get("face_min_size_px", 28))
        self.face_min_score = float(v.get("face_min_score", 0.010))
        self.mediapipe_face_enabled = bool(v.get("mediapipe_face_enabled", True))
        self.mediapipe_face_min_score = float(v.get("mediapipe_face_min_score", 0.55))
        self.fisheye_center_crop = float(v.get("fisheye_center_crop", 0.72))
        self.mediapipe_face = None
        if self.mediapipe_face_enabled:
            self.mediapipe_face = MediaPipeFaceDetector(
                v.get("mediapipe_face_model_path", "models/blaze_face_short_range.tflite"),
                min_confidence=self.mediapipe_face_min_score,
            )
        self.upperbody_scale_factor = float(v.get("upperbody_scale_factor", 1.04))
        self.upperbody_lock_enabled = bool(v.get("upperbody_lock_enabled", False))
        self.upperbody_min_neighbors = int(v.get("upperbody_min_neighbors", 3))
        self.upperbody_min_size_px = int(v.get("upperbody_min_size_px", 55))
        self.person_confirm_frames = int(v.get("person_confirm_frames", 2))
        self.person_center_radius_px = float(v.get("person_center_radius_px", 310))
        self.person_min_score = float(v.get("person_min_score", 0.018))
        self.person_max_v_ratio = float(v.get("person_max_v_ratio", 0.72))
        self._face_candidate_count = 0
        self._person_candidate_count = 0
        self._wave_candidate_count = 0
        self.reader = MjpegReader(self.url)
        hz = float(config.get("vision", {}).get("hz", 15))
        self.fx = OneEuro(hz, config.get("vision", {}).get("filter_min_cutoff", 1.0), config.get("vision", {}).get("filter_beta", 0.04))
        self.fy = OneEuro(hz, config.get("vision", {}).get("filter_min_cutoff", 1.0), config.get("vision", {}).get("filter_beta", 0.04))
        self.bg = None
        self.last_debug = {}
        self.last_target = Target(False)
        self._last_frame_sequence = None
        self.face = None
        self.upperbody = None
        if hasattr(cv2, "CascadeClassifier"):
            self.face = self._load_cascade(
                v.get("face_cascade_path"),
                [
                    "haarcascade_frontalface_default.xml",
                    "haarcascade_frontalface_alt2.xml",
                    "haarcascade_profileface.xml",
                ],
                "face_cascade_path",
            )
            if self.upperbody_lock_enabled:
                self.upperbody = self._load_cascade(
                    v.get("upperbody_cascade_path"),
                    ["haarcascade_upperbody.xml", "haarcascade_fullbody.xml"],
                    "upperbody_cascade_path",
                )

    def _load_cascade(self, configured_path, names, attr_name):
        candidates = []
        if configured_path:
            candidates.append(Path(str(configured_path)))
        if hasattr(cv2, "data"):
            haar_dir = Path(getattr(cv2.data, "haarcascades", ""))
            candidates.extend([haar_dir / name for name in names])
        for base in [Path("/usr/share/opencv4/haarcascades")]:
            candidates.extend([base / name for name in names])
        for path in candidates:
            if not path or not path.exists():
                continue
            cascade = cv2.CascadeClassifier(str(path))
            if not cascade.empty():
                setattr(self, attr_name, str(path))
                return cascade
        setattr(self, attr_name, None)
        return None

    def open(self):
        self.reader.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            frame, error = self.reader.latest()
            if frame is not None:
                return True
            time.sleep(0.1)
        return False

    def close(self):
        self.reader.close()
        if self.mediapipe_face is not None:
            self.mediapipe_face.close()

    def read_frame(self):
        if hasattr(self.reader, "latest_packet"):
            frame, error, sequence, received_at = self.reader.latest_packet()
        else:
            frame, error = self.reader.latest()
            sequence, received_at = None, time.time()
        if frame is None:
            if self.allow_health_fallback:
                target, health_error = self._read_health_target()
                return target, None, error or health_error
            return Target(False, w=self.width, h=self.height, kind="vision_stream_unavailable", ts=time.time()), None, error
        now = time.time()
        frame_age = now - float(received_at or 0.0)
        if received_at and frame_age > self.max_frame_age_s:
            stale_error = f"camera frame stale ({frame_age:.2f}s)"
            return (
                Target(False, w=frame.shape[1], h=frame.shape[0], kind="vision_frame_stale", ts=now),
                frame,
                error or stale_error,
            )
        if sequence is not None and sequence == self._last_frame_sequence:
            held = self._held_target()
            if held.found:
                return held, frame, error
            return (
                Target(False, w=frame.shape[1], h=frame.shape[0], kind="vision_frame_duplicate", ts=now),
                frame,
                error,
            )
        self._last_frame_sequence = sequence
        target = self.detect(frame)
        if not target.found and self.allow_health_fallback:
            health_target, _health_error = self._read_health_target()
            if health_target.found:
                return health_target, frame, error
        return target, frame, error

    def _read_health_target(self):
        try:
            with urllib.request.urlopen(self.health_url, timeout=1.0) as response:
                data = json.loads(response.read().decode("utf-8"))
            detection = data.get("detection") or {}
            targets = detection.get("targets") or []
            if not targets:
                return Target(False, w=self.width, h=self.height, kind="none", ts=time.time()), None

            def rank(item):
                label = str(item.get("label", "")).lower()
                try:
                    label_rank = self.prefer_labels.index(label)
                except ValueError:
                    label_rank = len(self.prefer_labels)
                score = float(item.get("score", 0.0) or 0.0)
                return (label_rank, -score)

            item = sorted(targets, key=rank)[0]
            centroid = item.get("centroid_xy") or []
            if len(centroid) < 2:
                bbox = item.get("bbox_xyxy") or []
                if len(bbox) == 4:
                    centroid = [(float(bbox[0]) + float(bbox[2])) / 2, (float(bbox[1]) + float(bbox[3])) / 2]
            if len(centroid) < 2:
                return Target(False, w=self.width, h=self.height, kind="none", ts=time.time()), "health target has no centroid"
            label = str(item.get("label", "vision_target"))
            return Target(
                True,
                self.fx(float(centroid[0])),
                self.fy(float(centroid[1])),
                self.width,
                self.height,
                float(item.get("score", 0.0) or 0.0),
                f"vision_{label}",
                time.time(),
            ), None
        except Exception as exc:
            return Target(False, w=self.width, h=self.height, kind="vision_unavailable", ts=time.time()), str(exc)

    def detect(self, frame):
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.mediapipe_face is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            crop_scale = max(0.30, min(1.0, self.fisheye_center_crop))
            x_margin = int((1.0 - crop_scale) * w / 2)
            y_margin = int((1.0 - crop_scale) * h / 2)
            reference = None
            if self.last_target.found:
                lock_age = time.time() - float(self.last_target.ts or 0.0)
                if lock_age <= self.target_hold_s:
                    reference = (self.last_target.u, self.last_target.v)
            mp_target, mp_debug = self.mediapipe_face.detect_crop(
                rgb,
                (x_margin, y_margin, w - x_margin, h - y_margin),
                reference=reference,
            )
            mp_debug["detect_crop"] = (x_margin, y_margin, w - x_margin, h - y_margin)
            if mp_target.found and self._front_person_candidate_allowed(
                mp_target.u,
                mp_target.v,
                w,
                h,
                mp_target.score,
                min_score=self.mediapipe_face_min_score,
            ):
                if not self._near_existing_lock(mp_target.u, mp_target.v):
                    held = self._held_target()
                    if held.found:
                        mp_debug["rejected"] = "mediapipe_far_from_lock"
                        self.last_debug = mp_debug
                        return held
                target = Target(
                    True,
                    self.fx(float(mp_target.u)),
                    self.fy(float(mp_target.v)),
                    w,
                    h,
                    mp_target.score,
                    "mediapipe_face",
                    time.time(),
                )
                self.last_target = target
                self._face_candidate_count = self.person_confirm_frames
                self._wave_candidate_count = 0
                self._person_candidate_count = 0
                self.last_debug = mp_debug
                return target
        faces = self.face.detectMultiScale(
            gray,
            self.face_scale_factor,
            self.face_min_neighbors,
            minSize=(self.face_min_size_px, self.face_min_size_px),
        ) if self.face is not None and not self.face.empty() else []
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
            raw_u = float(x + fw / 2)
            raw_v = float(y + fh / 2)
            score = float(fw * fh) / (w * h)
            if not self._front_person_candidate_allowed(raw_u, raw_v, w, h, score, min_score=self.face_min_score):
                self._face_candidate_count = 0
                held = self._held_target()
                if held.found:
                    self.last_debug = {
                        "mask": np.zeros_like(gray),
                        "bbox": (int(x), int(y), int(fw), int(fh)),
                        "contours": [],
                        "person_bbox": (int(x), int(y), int(fw), int(fh)),
                        "raw_target": (raw_u, raw_v),
                        "rejected": "face_not_front_person",
                    }
                    return held
                return Target(False, w=w, h=h, kind="face_not_front_person", ts=time.time())
            if not self._near_existing_lock(raw_u, raw_v):
                held = self._held_target()
                if held.found:
                    self._face_candidate_count = 0
                    self.last_debug = {
                        "mask": np.zeros_like(gray),
                        "bbox": (int(x), int(y), int(fw), int(fh)),
                        "contours": [],
                        "person_bbox": (int(x), int(y), int(fw), int(fh)),
                        "raw_target": (raw_u, raw_v),
                        "rejected": "far_from_lock",
                    }
                    return held
            self._face_candidate_count += 1
            if self._face_candidate_count < self.person_confirm_frames:
                self.last_debug = {
                    "mask": np.zeros_like(gray),
                    "bbox": (int(x), int(y), int(fw), int(fh)),
                    "contours": [],
                    "person_bbox": (int(x), int(y), int(fw), int(fh)),
                    "raw_target": (float(x + fw / 2), float(y + fh / 2)),
                    "candidate_count": self._face_candidate_count,
                }
                held = self._held_target()
                if held.found:
                    return held
                return Target(False, w=w, h=h, kind="face_candidate", ts=time.time())
            target = Target(True, self.fx(raw_u), self.fy(raw_v), w, h, score, "face", time.time())
            self.last_target = target
            self._face_candidate_count = self.person_confirm_frames
            self._wave_candidate_count = 0
            self._person_candidate_count = 0
            self.last_debug = {
                "mask": np.zeros_like(gray),
                "bbox": (int(x), int(y), int(fw), int(fh)),
                "contours": [],
                "person_bbox": (int(x), int(y), int(fw), int(fh)),
                "raw_target": (float(x + fw / 2), float(y + fh / 2)),
            }
            return target
        bodies = self.upperbody.detectMultiScale(
            gray,
            self.upperbody_scale_factor,
            self.upperbody_min_neighbors,
            minSize=(self.upperbody_min_size_px, self.upperbody_min_size_px),
        ) if self.upperbody is not None and not self.upperbody.empty() else []
        if len(bodies):
            held = self._held_target()
            if held.found and str(held.kind).startswith("mediapipe_face"):
                self.last_debug = {
                    "mask": np.zeros_like(gray),
                    "bbox": None,
                    "contours": [],
                    "rejected": "upperbody_deferred_to_mediapipe_face_lock",
                }
                return held
            x, y, bw, bh = max(bodies, key=lambda r: r[2] * r[3])
            raw_u = float(x + bw / 2)
            raw_v = float(y + bh * 0.28)
            score = float(bw * bh) / float(max(1, w * h))
            if self._front_person_candidate_allowed(raw_u, raw_v, w, h, score):
                self._person_candidate_count += 1
            else:
                self._person_candidate_count = 0
                self._face_candidate_count = 0
            self.last_debug = {
                "mask": np.zeros_like(gray),
                "bbox": (int(x), int(y), int(bw), int(bh)),
                "contours": [],
                "person_bbox": (int(x), int(y), int(bw), int(bh)),
                "raw_target": (raw_u, raw_v),
            }
            if self._person_candidate_count >= self.person_confirm_frames:
                if not self._near_existing_lock(raw_u, raw_v):
                    held = self._held_target()
                    if held.found:
                        self.last_debug["rejected"] = "far_from_lock"
                        return held
                target = Target(True, self.fx(raw_u), self.fy(raw_v), w, h, score, "front_person_lock", time.time())
                self.last_target = target
                self._wave_candidate_count = 0
                self._face_candidate_count = 0
                return target
            held = self._held_target()
            if held.found:
                return held
            return Target(False, w=w, h=h, kind="front_person_candidate", ts=time.time())
        blur = cv2.GaussianBlur(gray, (21, 21), 0)
        if self.bg is None:
            self.bg = blur.astype("float")
            self.last_debug = {
                "mask": np.zeros_like(gray),
                "bbox": None,
                "contours": [],
            }
            return Target(False, w=w, h=h, kind="none", ts=time.time())
        cv2.accumulateWeighted(blur, self.bg, 0.03)
        diff = cv2.absdiff(blur, cv2.convertScaleAbs(self.bg))
        _, mask = cv2.threshold(diff, 24, 255, cv2.THRESH_BINARY)
        mask = cv2.dilate(mask, None, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [c for c in contours if cv2.contourArea(c) >= self.min_area]
        if not contours:
            self.last_debug = {
                "mask": mask,
                "bbox": None,
                "contours": contours,
            }
            held = self._held_target()
            if held.found:
                return held
            self.fx.reset()
            self.fy.reset()
            return Target(False, w=w, h=h, kind="none", ts=time.time())
        contour = max(contours, key=cv2.contourArea)
        x, y, cw, ch = cv2.boundingRect(contour)
        u = self.fx(x + cw / 2)
        v = self.fy(y + ch / 2)
        motion = Target(True, u, v, w, h, float(cv2.contourArea(contour)) / (w * h), "person_motion", time.time())
        self.last_debug = {
            "mask": mask,
            "bbox": (int(x), int(y), int(cw), int(ch)),
            "contours": contours,
            "raw_target": (float(x + cw / 2), float(y + ch / 2)),
        }
        if not self._motion_allowed(motion):
            held = self._held_target()
            if held.found:
                return held
            return Target(False, w=w, h=h, kind="motion_without_face_lock", ts=time.time())
        held = self._held_target()
        if held.found and str(held.kind).startswith("mediapipe_face"):
            return held
        if self.last_target.found and str(self.last_target.kind).startswith(("wave_lock", "front_person_lock")):
            motion.kind = str(self.last_target.kind).replace("_hold", "")
        self.last_target = motion
        return motion

    def _front_person_candidate_allowed(self, u, v, w, h, score, min_score=None):
        cx = float(w) / 2.0
        cy = float(h) / 2.0
        dx = float(u) - cx
        dy = float(v) - cy
        near_center = (dx * dx + dy * dy) ** 0.5 <= self.person_center_radius_px
        required = self.person_min_score if min_score is None else float(min_score)
        plausible_head_height = float(v) <= float(h) * self.person_max_v_ratio
        return near_center and plausible_head_height and float(score or 0.0) >= required

    def _near_existing_lock(self, u, v):
        if not self.last_target.found:
            return True
        age = time.time() - float(self.last_target.ts or 0.0)
        if age > self.target_hold_s:
            return True
        kind = str(self.last_target.kind)
        if not kind.startswith(("face", "mediapipe_face", "front_person_lock", "wave_lock", "person_motion_hold")):
            return True
        dx = float(u) - float(self.last_target.u)
        dy = float(v) - float(self.last_target.v)
        return (dx * dx + dy * dy) ** 0.5 <= self.motion_lock_radius_px

    def _motion_allowed(self, motion):
        if not self.motion_requires_face_lock:
            return True
        if not self.last_target.found:
            return self._maybe_wave_lock(motion)
        if not str(self.last_target.kind).startswith(("face", "mediapipe_face", "face_hold", "person_motion_hold", "wave_lock", "front_person_lock")):
            return self._maybe_wave_lock(motion)
        age = time.time() - float(self.last_target.ts or 0.0)
        if age > self.target_hold_s:
            return self._maybe_wave_lock(motion)
        dx = float(motion.u) - float(self.last_target.u)
        dy = float(motion.v) - float(self.last_target.v)
        return (dx * dx + dy * dy) ** 0.5 <= self.motion_lock_radius_px

    def _maybe_wave_lock(self, motion):
        if not self.wave_lock_enabled:
            self._wave_candidate_count = 0
            return False
        cx = float(motion.w or self.width) / 2.0
        cy = float(motion.h or self.height) / 2.0
        dx = float(motion.u) - cx
        dy = float(motion.v) - cy
        near_center = (dx * dx + dy * dy) ** 0.5 <= self.wave_lock_center_radius_px
        strong = float(motion.score or 0.0) >= self.wave_lock_min_score
        if not (near_center and strong):
            self._wave_candidate_count = 0
            return False
        self._wave_candidate_count += 1
        if self._wave_candidate_count < self.wave_lock_frames:
            return False
        self.last_target = Target(
            True,
            motion.u,
            motion.v,
            motion.w,
            motion.h,
            motion.score,
            "wave_lock",
            time.time(),
        )
        return True

    def _held_target(self):
        if not self.last_target.found:
            return Target(False)
        age = time.time() - float(self.last_target.ts or 0.0)
        if age > self.target_hold_s:
            return Target(False)
        return Target(
            True,
            self.last_target.u,
            self.last_target.v,
            self.last_target.w,
            self.last_target.h,
            max(0.01, self.last_target.score * (1.0 - age / self.target_hold_s)),
            f"{self.last_target.kind}_hold",
            time.time(),
        )
