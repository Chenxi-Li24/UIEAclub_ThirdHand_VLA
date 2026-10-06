"""Read-only view of the running controller's exact observation, not a detector."""
from dataclasses import asdict
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time

import cv2


def observation_snapshot(runtime):
    motion_enabled = getattr(runtime, "adapter", None) is not None
    with runtime._lock:
        observation = runtime._latest
    if observation is None:
        return None, {"status": "waiting", "mode": runtime.mode,
                      "motion_enabled": motion_enabled}
    target = observation.target
    age = time.time() - target.ts
    usable = target.found and "hold" not in target.kind and 0 <= age <= runtime.max_observation_age_s
    debug = observation.debug or {}
    candidate = debug.get("lock_candidate")
    bbox = debug.get("bbox") or debug.get("person_bbox")
    if candidate:
        bbox = [candidate["u"] - candidate["w"] / 2, candidate["v"] - candidate["h"] / 2,
                candidate["w"], candidate["h"]]
    state = {"schema": "thirdhand-dummy-live-observation-v1", "status": "locked" if usable else "holding",
             "follow_target": debug.get("follow_target", "person"),
             "lock_state": debug.get("lock_state"), "face_count": debug.get("face_count"),
             "face_boxes_xywh": debug.get("face_boxes", []),
             "face_scores": debug.get("face_scores", []), "face_detector": debug.get("face_detector"),
             "auto_reacquire": debug.get("auto_reacquire"),
             "selection_generation": debug.get("selection_generation"),
             "frame_id": observation.frame_id, "observation_sequence": observation.sequence,
             "target": asdict(target), "bbox_xywh": list(bbox) if bbox is not None else None,
             "receive_age_ms": age * 1000, "detection_ms": observation.detection_ms,
             "mode": runtime.mode, "reason": runtime.last_reason,
             "motion_enabled": motion_enabled, "control": dict(runtime.metrics),
             "robot_joints_deg": list(runtime.joints) if motion_enabled else None,
             "preview_joints_deg": None if motion_enabled else list(runtime.joints),
             "used_by_last_command": observation.sequence == runtime.metrics.get("observation_sequence")}
    return observation.frame, state


def encode_frame(frame, state):
    if frame is None:
        return None
    out = frame.copy()
    h, w = out.shape[:2]
    color = (0, 255, 0) if state["status"] == "locked" else (0, 165, 255)
    for face_bbox in state.get("face_boxes_xywh", []):
        x, y, bw, bh = map(int, face_bbox)
        cv2.rectangle(out, (x, y), (x + bw, y + bh), (150, 150, 150), 1)
    bbox = state.get("bbox_xywh")
    if bbox:
        x, y, bw, bh = map(int, bbox)
        cv2.rectangle(out, (x, y), (x + bw, y + bh), color, 2)
    target = state["target"]
    if target["found"]:
        cv2.circle(out, (int(target["u"]), int(target["v"])), 7,
                   (0, 255, 255) if state["status"] == "locked" else (160, 160, 160), 2)
    cv2.drawMarker(out, (w // 2, h // 2), (255, 255, 255), cv2.MARKER_CROSS, 24, 1)
    mode = state["mode"] if state.get("motion_enabled") else "DRY RUN"
    text = f'{mode} | {target["kind"]} | seq={state["observation_sequence"]} | frame={state["frame_id"]}'
    cv2.putText(out, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1)
    ok, jpeg = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return jpeg.tobytes() if ok else None


class FollowTelemetryServer:
    def __init__(self, runtime, host="127.0.0.1", port=31024):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path not in ("/api/status", "/api/frame"):
                    self.send_error(404)
                    return
                frame, state = observation_snapshot(runtime)
                state.update(schema="thirdhand-dummy-live-observation-v1", pid=os.getpid(),
                             project_root=str(Path(__file__).resolve().parents[5]))
                body = state
                if self.path == "/api/frame":
                    jpeg = encode_frame(frame, state)
                    body = {"state": state, "jpeg_base64": base64.b64encode(jpeg).decode() if jpeg else None}
                encoded = json.dumps(body, allow_nan=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                try:
                    self.wfile.write(encoded)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="dummy-readonly-view", daemon=False)

    def start(self):
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
