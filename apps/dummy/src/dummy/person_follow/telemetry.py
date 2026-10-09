"""Read-only view of the running controller's exact observation, not a detector."""
from dataclasses import asdict
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import threading
import time

import cv2
from ..ok_gesture import SELECTION_GESTURE


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
    received_at = debug.get('frame_received_at') or target.ts
    frame_age = time.time()-received_at
    if usable:
        loss_reason = None
    elif not target.found:
        loss_reason = debug.get('rejected') if target.kind == 'face_person_lost' else target.kind
        loss_reason = loss_reason or target.kind
    elif not math.isfinite(age) or age < 0:
        loss_reason = 'invalid_observation_time'
    elif age > runtime.max_observation_age_s:
        loss_reason = 'observation_expired'
    else:
        loss_reason = 'held_observation'
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
             'selection_event': debug.get('selection_event'), 'loss_reason': loss_reason,
             "control_source": (debug.get("control_source") if usable else "LOST")
                               if debug.get("follow_target") == "face_person" else debug.get("control_source"),
             "person_track_id": debug.get("person_track_id"),
             "person_tracks": debug.get("person_tracks", []),
             "head_anchor": debug.get("head_anchor"),
             "association_reason": debug.get("rejected"),
             "person_detection_ms": debug.get("person_detection_ms"),
             "ok_switch": debug.get("ok_switch", {"enabled": False, "reason": "disabled"}),
             "frame_id": observation.frame_id, "observation_sequence": observation.sequence,
             "target": asdict(target), "bbox_xywh": list(bbox) if bbox is not None else None,
             "receive_age_ms": frame_age * 1000, 'observation_age_ms': age*1000,
             "detection_ms": observation.detection_ms,
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
    for person in state.get("person_tracks", []):
        x, y, bw, bh = map(int, person["bbox"])
        selected = person["track_id"] == state.get("person_track_id")
        body_color = (255, 200, 0) if selected and state['status'] == 'locked' else (110, 110, 110)
        cv2.rectangle(out, (x, y), (x+bw, y+bh), body_color, 1)
        cv2.putText(out, f'person {person["track_id"]}', (x, max(12, y-4)),
                    cv2.FONT_HERSHEY_SIMPLEX, .4, body_color, 1)
    for face_bbox in state.get("face_boxes_xywh", []):
        x, y, bw, bh = map(int, face_bbox)
        cv2.rectangle(out, (x, y), (x + bw, y + bh), (150, 150, 150), 1)
    gesture = state.get("ok_switch", {})
    for hand in gesture.get("hands", []):
        if state.get('loss_reason') in ('vision_frame_stale', 'observation_expired', 'vision_stream_unavailable'):
            continue
        x, y, bw, bh = [int(hand[k]) for k in ("x", "y", "w", "h")]
        cv2.rectangle(out, (x, y), (x+bw, y+bh), (255, 0, 255), 2)
        label = f'{SELECTION_GESTURE.upper()} {hand["score"]:.2f} owner={hand.get("person_track_id", "-")}'
        if hand.get("projected"):
            label += f' prev#{hand["source_frame_id"]}'
        cv2.putText(out, label, (x, max(12, y-4)),
                    cv2.FONT_HERSHEY_SIMPLEX, .4, (255, 0, 255), 1)
        for arm in hand.get('arms', []):
            for a, b in zip(arm, arm[1:]):
                cv2.line(out, tuple(map(int, a)), tuple(map(int, b)), (255, 0, 255), 2)
    gesture_reason = gesture.get('reason', 'disabled').replace('ok', SELECTION_GESTURE)
    cv2.putText(out, f'{SELECTION_GESTURE.upper()}: {gesture_reason} '
                    f'{gesture.get("progress", 0):.0%} person={gesture.get("person_track_id", "-")}',
                (10, 46), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 180, 255), 1)
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
    source = state.get("control_source") or target["kind"]
    text = f'{mode} | {source} | person={state.get("person_track_id")} | frame={state["frame_id"]}'
    cv2.putText(out, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1)
    loss = state.get('loss_reason')
    event = state.get('selection_event') or {}
    selection_type = SELECTION_GESTURE if event.get('type') == 'ok' else event.get('type', '-')
    detail = f'LOSS: {loss}' if loss else f'SELECT: {selection_type}'
    detail += f' | RX age: {state.get("receive_age_ms", 0):.0f}ms'
    cv2.putText(out, detail, (10, 68), cv2.FONT_HERSHEY_SIMPLEX, .42, color, 1)
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
