#!/usr/bin/env python3
"""Native Ubuntu desktop window for Dummy camera tracker visualization."""

import argparse
import os
import sys
import time
import tkinter as tk
from pathlib import Path

import cv2
from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.tracker import HumanTracker


def draw_overlay(frame, target, tracker, fps):
    if len(frame.shape) == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    cv2.drawMarker(frame, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 28, 1)
    if target.found:
        u, v = int(target.u), int(target.v)
        color = (0, 255, 255) if target.kind == "motion" else (0, 255, 0)
        cv2.circle(frame, (u, v), 12, color, 2)
        cv2.arrowedLine(frame, (cx, cy), (u, v), color, 2, tipLength=0.15)
        text = f"target={target.kind} err=({target.u - cx:+.0f},{target.v - cy:+.0f}) score={target.score:.3f}"
        cv2.putText(frame, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    else:
        cv2.putText(frame, "target=none; move/stand in view", (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.putText(frame, f"camera_index={tracker.index} fps={fps:.1f}", (12, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    return frame


class App:
    def __init__(self, root, tracker):
        self.root = root
        self.tracker = tracker
        self.label = tk.Label(root, bg="black")
        self.label.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="starting")
        tk.Label(root, textvariable=self.status, anchor="w").pack(fill="x")
        self.photo = None
        self.last = time.time()
        self.fps = 0.0
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.running = True
        self.tick()

    def tick(self):
        if not self.running:
            return
        ok, frame = self.tracker.cap.read()
        if ok:
            if self.tracker.mirror:
                frame = cv2.flip(frame, 1)
            # XVisio V4L2 YU12 appears green through OpenCV. For visualization/tracking,
            # use luminance by converting to gray and back to BGR before overlay.
            if len(frame.shape) == 3:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            target = self.tracker.read_frame(frame)
            now = time.time()
            dt = max(1e-6, now - self.last)
            self.fps = 0.9 * self.fps + 0.1 * (1 / dt) if self.fps else 1 / dt
            self.last = now
            frame = draw_overlay(frame, target, self.tracker, self.fps)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.photo = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.label.configure(image=self.photo)
            self.status.set(f"{target.kind if target.found else 'none'}")
        else:
            self.status.set("camera read timeout")
        self.root.after(30, self.tick)

    def close(self):
        self.running = False
        self.tracker.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--display", default=os.environ.get("DISPLAY") or ":0")
    args = parser.parse_args()
    os.environ.setdefault("DISPLAY", args.display)

    cfg = load_config()
    tracker = HumanTracker(cfg)
    if not tracker.open():
        raise SystemExit("camera did not open")

    root = tk.Tk()
    root.title("Dummy Camera Tracker")
    root.geometry("900x720")
    App(root, tracker)
    root.mainloop()


if __name__ == "__main__":
    main()
