#!/usr/bin/env python3
"""Browser-based tracker visualization for headless Ubuntu/OpenCV builds."""

import argparse
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.tracker import HumanTracker


class SharedFrame:
    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg = None
        self.status = "starting"
        self.stop = False


def draw_overlay(frame, target, tracker, fps):
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    cv2.drawMarker(frame, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 28, 1)
    cv2.line(frame, (cx - 45, cy), (cx + 45, cy), (80, 80, 80), 1)
    cv2.line(frame, (cx, cy - 45), (cx, cy + 45), (80, 80, 80), 1)
    if target.found:
        u, v = int(target.u), int(target.v)
        color = (0, 255, 255) if target.kind == "motion" else (0, 255, 0)
        cv2.circle(frame, (u, v), 12, color, 2)
        cv2.arrowedLine(frame, (cx, cy), (u, v), color, 2, tipLength=0.15)
        line = f"target={target.kind} err=({target.u - cx:+.0f},{target.v - cy:+.0f}) score={target.score:.3f}"
        cv2.putText(frame, line, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    else:
        cv2.putText(frame, "target=none; move/stand in view", (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.putText(frame, f"camera_index={tracker.index} fps={fps:.1f}", (12, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    return frame


def capture_loop(shared, config):
    tracker = HumanTracker(config)
    if not tracker.open():
        with shared.lock:
            shared.status = "camera did not open"
        return
    last = time.time()
    fps = 0.0
    try:
        while not shared.stop:
            ok, frame = tracker.cap.read()
            if not ok:
                with shared.lock:
                    shared.status = "camera read timeout"
                time.sleep(0.1)
                continue
            if tracker.mirror:
                frame = cv2.flip(frame, 1)
            target = tracker.read_frame(frame)
            now = time.time()
            dt = max(1e-6, now - last)
            fps = 0.9 * fps + 0.1 * (1 / dt) if fps else 1 / dt
            last = now
            frame = draw_overlay(frame, target, tracker, fps)
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if ok:
                with shared.lock:
                    shared.jpeg = encoded.tobytes()
                    shared.status = f"{target.kind if target.found else 'none'}"
            time.sleep(0.02)
    finally:
        tracker.close()


def make_handler(shared):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            if self.path in {"/", "/index.html"}:
                body = b"""<!doctype html><title>Dummy Camera Tracker</title>
<style>body{background:#111;color:#ddd;font-family:sans-serif} img{max-width:96vw;border:1px solid #444}</style>
<h2>Dummy Camera Tracker</h2>
<p>Yellow/green marker = target, white cross = image center. Refresh if stream stalls.</p>
<img src="/stream.mjpg">"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/status":
                with shared.lock:
                    body = shared.status.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path != "/stream.mjpg":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            while not shared.stop:
                with shared.lock:
                    jpeg = shared.jpeg
                if jpeg is None:
                    time.sleep(0.05)
                    continue
                try:
                    self.wfile.write(b"--frame\nContent-Type: image/jpeg\nContent-Length: " + str(len(jpeg)).encode() + b"\n\n" + jpeg + b"\n")
                    time.sleep(0.05)
                except BrokenPipeError:
                    break
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    cfg = load_config()
    shared = SharedFrame()
    thread = threading.Thread(target=capture_loop, args=(shared, cfg), daemon=True)
    thread.start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(shared))
    print(f"[dummy] camera visualization: http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shared.stop = True
        server.server_close()


if __name__ == "__main__":
    main()
