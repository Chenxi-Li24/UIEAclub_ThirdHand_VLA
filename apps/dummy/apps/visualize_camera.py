#!/usr/bin/env python3
"""Visualize the Dummy camera tracker without moving the robot."""

import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.tracker import HumanTracker


def main():
    cfg = load_config()
    tracker = HumanTracker(cfg)
    if not tracker.open():
        raise SystemExit("camera did not open; check camera_index in configs/dum_e_touch_r1.yaml")

    window = "Dummy camera tracker"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    last = time.time()
    fps = 0.0

    try:
        while True:
            cap = tracker.cap
            ok, frame = cap.read() if cap is not None else (False, None)
            if not ok:
                # tracker.read() already tried once; keep UI responsive on transient camera timeout.
                key = cv2.waitKey(30) & 0xFF
                if key in (ord("q"), 27):
                    break
                continue

            if tracker.mirror:
                frame = cv2.flip(frame, 1)
            target = tracker.read_frame(frame)
            h, w = frame.shape[:2]
            now = time.time()
            dt = max(1e-6, now - last)
            fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt
            last = now

            cx, cy = w // 2, h // 2
            cv2.drawMarker(frame, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 28, 1)
            cv2.line(frame, (cx - 45, cy), (cx + 45, cy), (80, 80, 80), 1)
            cv2.line(frame, (cx, cy - 45), (cx, cy + 45), (80, 80, 80), 1)

            if target.found:
                u, v = int(target.u), int(target.v)
                color = (0, 255, 255) if target.kind == "motion" else (0, 255, 0)
                cv2.circle(frame, (u, v), 12, color, 2)
                cv2.arrowedLine(frame, (cx, cy), (u, v), color, 2, tipLength=0.15)
                cv2.putText(
                    frame,
                    f"target={target.kind} err=({target.u - cx:+.0f},{target.v - cy:+.0f}) score={target.score:.3f}",
                    (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2,
                )
            else:
                cv2.putText(
                    frame,
                    "target=none  move/stand in view; q or ESC exits",
                    (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255),
                    2,
                )

            cv2.putText(
                frame,
                f"camera_index={tracker.index}  fps={fps:.1f}",
                (12, h - 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                1,
            )

            cv2.imshow(window, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
    finally:
        tracker.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
