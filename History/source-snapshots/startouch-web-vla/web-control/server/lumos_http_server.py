#!/usr/bin/env python3
"""Camera-only Lumos MJPEG service.

This process opens one explicitly configured V4L2 device and exposes read-only
HTTP endpoints. It has no robot, CAN, WebSocket, or Startouch dependency.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple

import cv2
import numpy as np


def discover_lumos_device(
    sys_class: Path = Path("/sys/class/video4linux"),
    dev_root: Path = Path("/dev"),
) -> str:
    """Find the XVisio capture node without relying on V4L enumeration order."""

    try:
        entries = sorted(sys_class.glob("video*"), key=lambda item: item.name)
    except OSError:
        entries = []
    for entry in entries:
        try:
            product = (entry / "name").read_text(encoding="utf-8").strip().lower()
            interface_index = (entry / "index").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        device = dev_root / entry.name
        if "xvisio" in product and interface_index == "0" and device.exists():
            return str(device)
    raise RuntimeError("cannot discover the XVisio Lumos capture interface")


def decode_lumos_frame(frame: np.ndarray, *, width: int, height: int) -> np.ndarray:
    """Return BGR for either a native BGR frame or an I420/YU12 byte plane."""

    if frame.shape == (height, width, 3) and frame.dtype == np.uint8:
        return frame.copy()
    if frame.shape == (height * 3 // 2, width) and frame.dtype == np.uint8:
        return cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
    raise ValueError(
        f"unexpected Lumos frame layout {frame.shape} {frame.dtype}; "
        f"expected {(height, width, 3)} BGR or {(height * 3 // 2, width)} I420"
    )


class LumosCapture:
    def __init__(
        self,
        device: str,
        width: int,
        height: int,
        output_size: int,
        jpeg_quality: int,
        target_fps: float,
    ) -> None:
        self.device = device
        self.width = width
        self.height = height
        self.output_size = output_size
        self.jpeg_quality = jpeg_quality
        self.target_fps = target_fps
        self.condition = threading.Condition()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.jpeg: Optional[bytes] = None
        self.sequence = 0
        self.last_frame_monotonic = 0.0
        self.last_frame_monotonic_ns = 0
        self.last_error: Optional[str] = None
        self.raw_shape: Optional[Tuple[int, ...]] = None

    def start(self) -> None:
        if self.thread is not None:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, name="lumos-capture", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        with self.condition:
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=3.0)

    def _publish_error(self, message: str) -> None:
        with self.condition:
            self.last_error = message
            self.condition.notify_all()

    def _run(self) -> None:
        capture = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not capture.isOpened():
            self._publish_error(f"cannot open {self.device}")
            return
        try:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YU12"))
            capture.set(cv2.CAP_PROP_CONVERT_RGB, 0)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            consecutive_failures = 0
            while self.running:
                frame_started = time.monotonic()
                ok, raw = capture.read()
                if not ok or raw is None:
                    consecutive_failures += 1
                    self._publish_error(f"capture read failed ({consecutive_failures})")
                    time.sleep(min(0.02 * consecutive_failures, 0.5))
                    continue
                try:
                    bgr = decode_lumos_frame(raw, width=self.width, height=self.height)
                except ValueError as error:
                    self._publish_error(str(error))
                    time.sleep(0.1)
                    continue
                resized = cv2.resize(
                    bgr,
                    (self.output_size, self.output_size),
                    interpolation=cv2.INTER_AREA,
                )
                encoded, jpeg = cv2.imencode(
                    ".jpg",
                    resized,
                    [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
                )
                if not encoded:
                    self._publish_error("JPEG encoding failed")
                    continue
                consecutive_failures = 0
                with self.condition:
                    self.jpeg = jpeg.tobytes()
                    self.sequence += 1
                    self.last_frame_monotonic_ns = time.monotonic_ns()
                    self.last_frame_monotonic = self.last_frame_monotonic_ns / 1_000_000_000
                    self.last_error = None
                    self.raw_shape = tuple(raw.shape)
                    self.condition.notify_all()
                remaining = (1.0 / self.target_fps) - (time.monotonic() - frame_started)
                if remaining > 0.0:
                    time.sleep(remaining)
        finally:
            capture.release()

    def wait_for_frame(self, after_sequence: int, timeout: float) -> tuple[Optional[bytes], int]:
        jpeg, sequence, _ = self.wait_for_snapshot(after_sequence, timeout)
        return jpeg, sequence

    def wait_for_snapshot(
        self,
        after_sequence: int,
        timeout: float,
    ) -> tuple[Optional[bytes], int, int]:
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.running and self.sequence <= after_sequence:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    break
                self.condition.wait(remaining)
            return self.jpeg, self.sequence, self.last_frame_monotonic_ns

    def status(self) -> dict:
        with self.condition:
            age = None
            if self.last_frame_monotonic:
                age = max(0.0, time.monotonic() - self.last_frame_monotonic)
            return {
                "ready": self.jpeg is not None and age is not None and age < 2.0,
                "device": self.device,
                "target_fps": self.target_fps,
                "sequence": self.sequence,
                "frame_age_s": age,
                "raw_shape": self.raw_shape,
                "last_error": self.last_error,
            }


def make_handler(capture: LumosCapture):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ThirdHandLumos/1.0"

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = self.path.split("?", 1)[0]
            if path == "/health":
                payload = (json.dumps(capture.status(), sort_keys=True) + "\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self._cors()
                self.end_headers()
                self.wfile.write(payload)
                return
            if path == "/frame.jpg":
                jpeg, sequence, monotonic_ns = capture.wait_for_snapshot(
                    -1,
                    timeout=5.0,
                )
                if jpeg is None or monotonic_ns <= 0:
                    payload = (json.dumps(capture.status(), sort_keys=True) + "\n").encode(
                        "utf-8"
                    )
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self._cors()
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("X-Lumos-Sequence", str(sequence))
                self.send_header("X-Lumos-Monotonic-Ns", str(monotonic_ns))
                self._cors()
                self.end_headers()
                self.wfile.write(jpeg)
                return
            if path != "/camera_lumos":
                self.send_error(404)
                return

            jpeg, sequence = capture.wait_for_frame(-1, timeout=5.0)
            if jpeg is None:
                payload = (json.dumps(capture.status(), sort_keys=True) + "\n").encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self._cors()
                self.end_headers()
                self.wfile.write(payload)
                return

            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self._cors()
            self.end_headers()
            try:
                while capture.running:
                    jpeg, next_sequence = capture.wait_for_frame(sequence, timeout=2.0)
                    if jpeg is None or next_sequence == sequence:
                        continue
                    sequence = next_sequence
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                return

        def log_message(self, message_format: str, *args) -> None:
            sys.stderr.write(
                "%s - - [%s] %s\n"
                % (self.address_string(), self.log_date_time_string(), message_format % args)
            )

    return Handler


def main() -> int:
    device = os.environ.get("LUMOS_DEVICE") or discover_lumos_device()
    width = int(os.environ.get("LUMOS_WIDTH", "1280"))
    height = int(os.environ.get("LUMOS_HEIGHT", "1280"))
    output_size = int(os.environ.get("LUMOS_OUTPUT_SIZE", "480"))
    jpeg_quality = int(os.environ.get("LUMOS_JPEG_QUALITY", "70"))
    target_fps = float(os.environ.get("LUMOS_FPS", "15"))
    host = os.environ.get("LUMOS_HTTP_HOST", "0.0.0.0")
    port = int(os.environ.get("LUMOS_HTTP_PORT", "3001"))
    if not 1.0 <= target_fps <= 30.0:
        raise ValueError("LUMOS_FPS must be between 1 and 30")
    capture = LumosCapture(device, width, height, output_size, jpeg_quality, target_fps)
    server = ThreadingHTTPServer((host, port), make_handler(capture))
    server.daemon_threads = True

    def stop(_signum, _frame) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    capture.start()
    sys.stderr.write(f"Lumos HTTP listening on {host}:{port}, device={device}\n")
    sys.stderr.flush()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        capture.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
