#!/usr/bin/env python3
"""Compare two face detectors on identical camera frames; no robot connection."""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.config import load_config
from dummy.mediapipe_face import MediaPipeFaceDetector
from dummy.vision_service_tracker import MjpegReader
from dummy.yunet_face import YuNetFaceDetector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.frames <= 300:
        parser.error("--frames must be 1..300")
    config = load_config()
    vision = config["vision_service"]
    models = {"blazeface": MediaPipeFaceDetector(vision["mediapipe_face_model_path"], min_confidence=.2),
              "yunet": YuNetFaceDetector("local/models/vision/face_detection_yunet_2026may.onnx", min_confidence=.8)}
    reader = MjpegReader(vision["mjpeg_url"])
    reader.start()
    last_id = None
    completed = 0
    deadline = time.monotonic() + args.frames * .5 + 10
    try:
        while completed < args.frames and time.monotonic() < deadline:
            frame, error, frame_id, received_at = reader.latest_packet()
            if frame is None or frame_id == last_id or time.time() - received_at > .5:
                time.sleep(.05)
                continue
            last_id = frame_id
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            row = {"frame_id": frame_id, "error": error}
            for name, detector in models.items():
                started = time.monotonic()
                faces = detector.detect_all(rgb)
                row[name] = {"ms": round((time.monotonic() - started) * 1000, 2),
                             "faces": [{"bbox": debug["bbox"], "score": round(target.score, 4)}
                                       for target, debug in faces]}
            print(json.dumps(row), flush=True)
            completed += 1
        return 0 if completed == args.frames else 1
    finally:
        reader.close()
        for detector in models.values():
            detector.close()


if __name__ == "__main__":
    raise SystemExit(main())
