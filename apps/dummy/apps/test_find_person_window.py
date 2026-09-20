#!/usr/bin/env python3
"""Native window to test person/motion finding."""

import argparse
import os
import sys
import tkinter as tk
from pathlib import Path

import cv2
from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.display import prepare_color_frame
from dummy.tracker import HumanTracker
from dummy.vision_service_tracker import VisionServiceTracker


def overlay(frame, target, debug=None, cfg=None):
    debug = debug or {}
    cfg = cfg or {}
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    dzx = int(w * float(cfg.get("dead_zone_x_norm", 0.06)))
    dzy = int(h * float(cfg.get("dead_zone_y_norm", 0.06)))
    cv2.rectangle(frame, (cx - dzx, cy - dzy), (cx + dzx, cy + dzy), (90, 90, 90), 1)
    cv2.drawMarker(frame, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 30, 1)
    raw = debug.get("raw_target")
    crop = debug.get("detect_crop")
    if crop:
        x0, y0, x1, y1 = [int(v) for v in crop]
        cv2.rectangle(frame, (x0, y0), (x1, y1), (255, 180, 0), 1)
        label = "fisheye full-frame detection" if x0 <= 1 and y0 <= 1 and x1 >= w - 1 and y1 >= h - 1 else "fisheye detection crop"
        cv2.putText(frame, label, (x0 + 8, max(18, y0 + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 180, 0), 1)
    if raw:
        cv2.drawMarker(frame, (int(raw[0]), int(raw[1])), (255, 0, 255), cv2.MARKER_DIAMOND, 18, 2)
        cv2.putText(frame, "raw", (int(raw[0]) + 8, int(raw[1]) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 0, 255), 1)
    if target.found:
        u, v = int(target.u), int(target.v)
        cv2.circle(frame, (u, v), 14, (0, 255, 255), 2)
        cv2.arrowedLine(frame, (cx, cy), (u, v), (0, 255, 255), 2)
        ex = target.u - cx
        ey = target.v - cy
        text = f"{target.kind} err=({ex:+.0f},{ey:+.0f}) norm=({ex/(w/2):+.2f},{ey/(h/2):+.2f}) score={target.score:.3f}"
        color = (0, 255, 255)
    else:
        text = f"{target.kind or 'none'} - no selected person"
        color = (0, 0, 255)
    cv2.putText(frame, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    rejected = debug.get("rejected")
    if rejected:
        cv2.putText(frame, f"reject: {rejected}", (12, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 130, 255), 2)
    return frame


def algorithm_view(frame, target, debug):
    if len(frame.shape) == 2:
        base = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    else:
        base = frame.copy()
    mask = debug.get("mask")
    if mask is not None:
        heat = cv2.applyColorMap(mask, cv2.COLORMAP_TURBO)
        active = mask > 0
        blended = cv2.addWeighted(base, 0.65, heat, 0.55, 0)
        base[active] = blended[active]
    contours = debug.get("contours") or []
    if contours:
        cv2.drawContours(base, contours, -1, (0, 255, 80), 2)
    bbox = debug.get("bbox")
    if bbox:
        x, y, w, h = bbox
        cv2.rectangle(base, (x, y), (x + w, y + h), (0, 255, 80), 2)
        cv2.putText(base, "person/bbox", (x, max(15, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 80), 1)
    return base


def blank_frame(target):
    import numpy as np

    w = int(target.w or 640)
    h = int(target.h or 480)
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.putText(frame, "Vision MJPEG stream unavailable", (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 180, 255), 2)
    cv2.putText(frame, "Using Vision Service /health target only", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 180, 255), 2)
    return overlay(frame, target)


class App:
    def __init__(self, root, tracker, source):
        self.root = root
        self.tracker = tracker
        self.source = source
        self.label = tk.Label(root, bg="black")
        self.label.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="starting")
        tk.Label(root, textvariable=self.status, anchor="w").pack(fill="x")
        self.photo = None
        self.cfg = load_config()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    def tick(self):
        if self.source == "direct":
            error = None
            frame = None
            if self.tracker.open():
                ok, frame = self.tracker.cap.read()
                if ok:
                    frame = prepare_color_frame(frame, mirror=self.tracker.mirror)
                    target = self.tracker.read_frame(frame)
                    frame = algorithm_view(frame, target, self.tracker.last_debug)
                else:
                    target = self.tracker.read()
                    error = "camera read failed"
            else:
                target = self.tracker.read()
                error = "camera open failed"
        else:
            target, frame, error = self.tracker.read_frame()
            if frame is not None:
                frame = algorithm_view(frame, target, getattr(self.tracker, "last_debug", {}))
        if frame is not None or target.found:
            if frame is None:
                frame = blank_frame(target)
            else:
                frame = overlay(frame, target, getattr(self.tracker, "last_debug", {}), self.cfg.get("follow", {}))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            img.thumbnail((1100, 800))
            self.photo = ImageTk.PhotoImage(img)
            self.label.configure(image=self.photo)
            self.status.set(f"{target.kind if target.found else 'none'} score={target.score:.3f} stream_error={error}")
        else:
            self.status.set(f"no frame: {error}")
        self.root.after(33, self.tick)

    def close(self):
        self.tracker.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--display", default=os.environ.get("DISPLAY") or ":1")
    parser.add_argument("--source", choices=("direct", "vision"), default="vision")
    args = parser.parse_args()
    os.environ.setdefault("DISPLAY", args.display)
    cfg = load_config()
    if args.source == "direct":
        tracker = HumanTracker(cfg)
    else:
        tracker = VisionServiceTracker(cfg)
    stream_opened = tracker.open()
    root = tk.Tk()
    root.title(f"Dummy Find Person Test - {args.source} {'open' if stream_opened else 'fallback'}")
    root.geometry("1100x850")
    App(root, tracker, args.source)
    root.mainloop()


if __name__ == "__main__":
    main()
