#!/usr/bin/env python3
"""Finite real-camera face check. Never constructs a robot adapter or SDK."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.config import load_config
from dummy.vision_service_tracker import VisionServiceTracker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=40)
    args = parser.parse_args()
    if not 1 <= args.frames <= 600:
        parser.error("--frames must be between 1 and 600")
    config = load_config()
    config.setdefault("vision_service", {})["follow_target"] = "face"
    tracker = VisionServiceTracker(config)
    samples = []
    try:
        if not tracker.open():
            raise RuntimeError("XVisio stream unavailable")
        for _ in range(args.frames):
            started = time.monotonic()
            target, _frame, error = tracker.read_frame()
            elapsed = (time.monotonic() - started) * 1000
            if target.kind != "vision_frame_duplicate":
                row = {"frame_id": tracker._last_frame_sequence, "kind": target.kind,
                       "found": target.found, "face_count": tracker.last_debug.get("face_count"),
                       "lock_state": tracker.last_debug.get("lock_state"),
                       "detection_ms": round(elapsed, 2), "error": error}
                samples.append(row)
                print(json.dumps(row), flush=True)
            time.sleep(max(0, .1 - (time.monotonic() - started)))
        usable = [row for row in samples if row["kind"] == "face_lock"]
        print(json.dumps({"motion_enabled": False, "samples": len(samples),
                          "face_locked_frames": len(usable),
                          "model_available": tracker.face_detector.available,
                          "body_detector_enabled": tracker.yolo_person.enabled}), flush=True)
        return 0 if samples and tracker.face_detector.available else 1
    finally:
        tracker.close()


if __name__ == "__main__":
    raise SystemExit(main())
