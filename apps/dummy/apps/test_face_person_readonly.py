#!/usr/bin/env python3
"""Finite FACE/BODY/LOST preview; never constructs a robot adapter or SDK."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.config import load_config
from dummy.person_follow.runtime import PersonFollowRuntime
from dummy.person_follow.telemetry import FollowTelemetryServer, observation_snapshot
from dummy.vision_service_tracker import VisionServiceTracker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--port", type=int, default=31025)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600 or not 1024 <= args.port <= 65535:
        parser.error("seconds must be 1..600; port must be 1024..65535")
    config = load_config()
    config.setdefault("vision_service", {})["follow_target"] = "face"
    config.setdefault("person_tracking", {})["enabled"] = True
    tracker = VisionServiceTracker(config)
    runtime = PersonFollowRuntime(None, config=config)
    server = FollowTelemetryServer(runtime, port=args.port)
    samples = []
    try:
        server.start()
        if not tracker.open():
            raise RuntimeError("XVisio stream unavailable")
        deadline = time.monotonic()+args.seconds
        while time.monotonic() < deadline:
            started = time.monotonic()
            target, frame, error = tracker.read_frame()
            elapsed = (time.monotonic()-started)*1000
            if target.kind != "vision_frame_duplicate":
                runtime.publish(target, frame=frame, frame_id=tracker._last_frame_sequence,
                                detection_ms=elapsed, debug=dict(tracker.last_debug))
                state = observation_snapshot(runtime)[1]
                row = {key: state.get(key) for key in ("control_source", "person_track_id", "face_count",
                       "detection_ms", "person_detection_ms", "receive_age_ms", "association_reason")}
                row.update(error=error, motion_enabled=False)
                samples.append(row)
                print(json.dumps(row), flush=True)
            time.sleep(max(0., .1-(time.monotonic()-started)))
        counts = {source: sum(row["control_source"] == source for row in samples)
                  for source in ("FACE", "BODY", "LOST")}
        print(json.dumps({"summary": counts, "samples": len(samples), "motion_enabled": False}), flush=True)
        return 0 if samples and tracker.yolo_person.available and tracker.face_detector.available else 1
    finally:
        server.close()
        tracker.close()


if __name__ == "__main__":
    raise SystemExit(main())
