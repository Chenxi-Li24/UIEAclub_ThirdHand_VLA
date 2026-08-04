#!/usr/bin/env python3
"""D435 registered-depth and RGB-debug bridge for proxy.js.

Communicates via:
  stdin  ← arm_state (JSON-lines, from proxy.js forwarding robot_state)
  fd:4   → events (JSON-lines: detection_result, camera_status, grasp_target)
  stdout → MJPEG stream (multipart JPEG, proxy.js routes to /camera)

Does NOT connect to the arm (no SingleArm). Arm pose arrives via stdin.
"""

import json
import math
import os
import sys
import time
import threading
import traceback
from typing import Any

import cv2
import numpy as np
import pyrealsense2 as rs

from vision.calibration_gate import audit_handeye_calibration, sdk_pose_transform

# ── Config from env ──────────────────────────────────────────
CALIB_FILE = os.path.expanduser(
    os.environ.get("CAMERA_CALIB_FILE", "~/calibration/d435_handeye_result.json")
)
YOLO_MODEL_PATH = os.environ.get("CAMERA_YOLO_MODEL", "yolov8n.pt")
DETECT_INTERVAL = int(os.environ.get("CAMERA_DETECT_INTERVAL", "10"))
DEBUG_DETECTION = os.environ.get("CAMERA_D435_DEBUG_DETECTION", "0") == "1"
JPEG_QUALITY = int(os.environ.get("CAMERA_JPEG_QUALITY", "70"))
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
DESK_Z = float(os.environ.get("CAMERA_DESK_Z", "0.0"))
SAFE_Z = float(os.environ.get("CAMERA_SAFE_Z", "0.12"))

# ── fd:4 event output ────────────────────────────────────────
EVENT_FD = int(os.environ.get("CAMERA_EVENT_FD", "3"))
_event_file = os.fdopen(EVENT_FD, "w", buffering=1, encoding="utf-8", closefd=False)
_event_lock = threading.Lock()


def emit(message_type: str, **payload: Any) -> None:
    message = {"type": message_type, **payload, "ts": int(time.time() * 1000)}
    with _event_lock:
        print(
            json.dumps(message, ensure_ascii=False, separators=(",", ":")),
            file=_event_file,
            flush=True,
        )


# ── Camera intrinsics (populated at startup) ─────────────────
FX: float | None = None
FY: float | None = None
U0: float | None = None
V0: float | None = None
DEPTH_SCALE: float | None = None

# ── Calibration ──────────────────────────────────────────────
T_flange_d435cam: np.ndarray = np.eye(4)
calibration_validated = False
calibration_reasons: tuple[str, ...] = ("calibration_not_loaded",)

# ── Shared state ─────────────────────────────────────────────
rgb_frame: np.ndarray | None = None
depth_data: np.ndarray | None = None
latest_arm_pos: list[float] | None = None  # [x, y, z]
latest_arm_euler: list[float] | None = None  # [r, p, y]
latest_arm_ts: float = 0.0
arm_lock = threading.Lock()
shutdown_flag = threading.Event()
jpeg_bytes: bytes | None = None
jpeg_lock = threading.Lock()
tracked_objects: dict[int, dict[str, Any]] = {}
next_track_id: int = 0
obj_lock = threading.Lock()


# ── YOLO tracking (simplified, from d435_grasp.py) ───────────
def iou(box1: tuple, box2: tuple) -> float:
    x1 = max(box1[0], box2[0]); y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2]); y2 = min(box1[3], box2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    a1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    a2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    return inter / (a1 + a2 - inter + 1e-6)


def update_tracking(new_boxes: list[dict]) -> dict[int, dict]:
    global tracked_objects, next_track_id
    if not new_boxes:
        tracked_objects = {}
        return {}

    matched: dict[int, dict] = {}
    used_new: set[int] = set()

    for tid, old in tracked_objects.items():
        best_iou_val, best_j = 0.0, -1
        for j, new_box in enumerate(new_boxes):
            if j in used_new:
                continue
            i = iou(old["box"], new_box["box"])
            if i > best_iou_val:
                best_iou_val, best_j = i, j
        if best_iou_val > 0.3:
            matched[tid] = new_boxes[best_j]
            used_new.add(best_j)

    new_tracked: dict[int, dict] = {}
    for tid, box_data in matched.items():
        new_tracked[tid] = box_data

    for j, box_data in enumerate(new_boxes):
        if j not in used_new:
            tid = next_track_id
            next_track_id += 1
            new_tracked[tid] = box_data

    tracked_objects = new_tracked
    return new_tracked


# ── Coordinate transforms ────────────────────────────────────
def build_transform(pos: list[float], euler: list[float]) -> np.ndarray:
    return sdk_pose_transform(pos, euler)


def T_base_d435cam() -> np.ndarray | None:
    """Compute camera pose in base frame from latest arm state."""
    with arm_lock:
        pos = latest_arm_pos
        euler = latest_arm_euler
        pose_age_s = time.monotonic() - latest_arm_ts
    if (
        pos is None
        or euler is None
        or pose_age_s > 0.25
        or not calibration_validated
    ):
        return None
    T_base_ee = build_transform(pos, euler)
    return T_base_ee @ T_flange_d435cam


def base_frame_position(u: float, v: float, x1: float, y1: float,
                        x2: float, y2: float) -> tuple[float, float, float] | None:
    """Compute object XY in robot base frame.

    Tries ray-plane intersection first (more accurate when camera looks at desk).
    Falls back to depth deprojection.
    """
    T_base_cam = T_base_d435cam()
    if T_base_cam is None or FX is None:
        return None

    # Pixel → unit ray in camera frame
    xn = (u - U0) / FX
    yn = (v - V0) / FY
    ray_cam = np.array([xn, yn, 1.0])
    ray_cam /= np.linalg.norm(ray_cam)

    R_base_cam = T_base_cam[:3, :3]
    cam_pos = T_base_cam[:3, 3]
    ray_base = R_base_cam @ ray_cam

    # Try ray-plane intersection
    if ray_base[2] < 0:  # Camera looking down
        if abs(ray_base[2]) < 1e-10:
            return None
        t = (DESK_Z - cam_pos[2]) / ray_base[2]
        if t > 0:
            p_base = cam_pos + t * ray_base
            return float(p_base[0]), float(p_base[1]), float(p_base[2])

    # Fallback: depth deprojection
    if depth_data is None or DEPTH_SCALE is None:
        return None
    uc = int(np.clip(u, 0, FRAME_WIDTH - 1))
    vc = int(np.clip(v, 0, FRAME_HEIGHT - 1))
    d_mm = float(depth_data[vc, uc])
    if d_mm <= 0 or d_mm > 5000:
        return None
    d = d_mm * DEPTH_SCALE
    p_cam = d * ray_cam
    p_base = T_base_cam @ np.append(p_cam, 1.0)
    return float(p_base[0]), float(p_base[1]), float(p_base[2])


# ── D435 capture + YOLO thread ──────────────────────────────
def capture_loop() -> None:
    global rgb_frame, depth_data, FX, FY, U0, V0, DEPTH_SCALE
    global jpeg_bytes, tracked_objects

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, FRAME_WIDTH, FRAME_HEIGHT, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, FRAME_WIDTH, FRAME_HEIGHT, rs.format.bgr8, 30)

    try:
        profile = pipeline.start(config)
    except Exception as e:
        emit("camera_error", message=f"D435 start failed: {e}")
        print(f"D435 start error: {e}", file=sys.stderr, flush=True)
        return

    color_stream = profile.get_stream(rs.stream.color).as_video_stream_profile()
    intr = color_stream.get_intrinsics()
    FX = intr.fx
    FY = intr.fy
    U0 = intr.ppx
    V0 = intr.ppy
    DEPTH_SCALE = profile.get_device().first_depth_sensor().get_depth_scale()

    # D435 RGB is debug/calibration only. Semantic identity belongs to Lumos.
    yolo_model = None
    yolo_ready = False
    if DEBUG_DETECTION:
        try:
            from ultralytics import YOLO

            yolo_model = YOLO(YOLO_MODEL_PATH)
            yolo_model.to("cpu")
            yolo_ready = True
        except Exception as e:
            emit("camera_error", message=f"D435 debug detector load failed: {e}")

    emit("camera_status",
         d435_ready=True,
         calibration_loaded=not np.array_equal(T_flange_d435cam, np.eye(4)),
         calibration_validated=calibration_validated,
         calibration_reasons=list(calibration_reasons),
         rgb_role="debug_only",
         depth_role="metric_depth",
         resolution=f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
         fx=FX, fy=FY,
         yolo_ready=yolo_ready,
    )

    align = rs.align(rs.stream.color)

    # Warm up
    for _ in range(30):
        pipeline.wait_for_frames()

    tick = 0
    colors = [(0, 255, 0), (255, 200, 0), (0, 200, 255),
              (255, 0, 200), (200, 255, 0)]

    while not shutdown_flag.is_set():
        try:
            frames = pipeline.wait_for_frames(timeout_ms=1000)
            aligned = align.process(frames)
            color_frame = aligned.get_color_frame()
            depth_f = aligned.get_depth_frame()

            if not color_frame or not depth_f:
                continue

            frame = np.asanyarray(color_frame.get_data())
            depth_data = np.asanyarray(depth_f.get_data())

            tick += 1

            # YOLO detection
            if yolo_ready and tick % DETECT_INTERVAL == 0:
                small = cv2.resize(frame, (320, 240))
                results = yolo_model(small, conf=0.25, verbose=False, imgsz=320,
                                     classes=[39, 40, 41, 44, 46, 47])

                new_boxes: list[dict] = []
                for r in results:
                    if r.boxes is None:
                        continue
                    for box in r.boxes:
                        cls_id = int(box.cls[0])
                        conf = float(box.conf[0])
                        xyxy = box.xyxy[0].cpu().numpy()
                        x1 = int(np.clip(xyxy[0] * 2, 0, FRAME_WIDTH - 1))
                        y1 = int(np.clip(xyxy[1] * 2, 0, FRAME_HEIGHT - 1))
                        x2 = int(np.clip(xyxy[2] * 2, 0, FRAME_WIDTH - 1))
                        y2 = int(np.clip(xyxy[3] * 2, 0, FRAME_HEIGHT - 1))
                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                        new_boxes.append({
                            "label": yolo_model.names.get(cls_id, "obj"),
                            "cx": cx, "cy": cy, "conf": conf,
                            "box": (x1, y1, x2, y2),
                        })

                with obj_lock:
                    tracks = update_tracking(new_boxes)

                # Emit detection result
                obj_list = []
                for tid, obj in sorted(tracks.items()):
                    d_mm = float(depth_data[obj["cy"], obj["cx"]]) if depth_data is not None else 0
                    obj_list.append({
                        "id": tid,
                        "label": obj["label"],
                        "conf": obj["conf"],
                        "cx": obj["cx"], "cy": obj["cy"],
                        "position_m": None,
                        "depth_m": d_mm * DEPTH_SCALE if DEPTH_SCALE and d_mm > 0 else None,
                        "source": "d435_rgb_debug",
                        "actionable": False,
                        "calibration_validated": calibration_validated,
                        "depth_valid": False,
                        "identity_confirmed": False,
                        "arm_stationary": False,
                        "reasons": ["d435_rgb_not_canonical", *calibration_reasons],
                        "observed_at_ms": int(time.time() * 1000),
                    })
                emit("detection_result", objects=obj_list, count=len(obj_list))
            else:
                with obj_lock:
                    tracks = dict(tracked_objects)

            # Draw
            out = frame.copy()
            for tid, obj in tracks.items():
                color = colors[tid % len(colors)]
                x1, y1, x2, y2 = obj["box"]
                cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
                cv2.putText(out,
                            f"#{tid} {obj['label']} [D435 RGB debug]",
                            (x1, max(y1 - 8, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
                cv2.circle(out, (obj["cx"], obj["cy"]), 4, color, -1)

            # Depth minimap
            depth_viz = np.clip(depth_data.astype(np.float32) / 3000.0 * 255,
                                0, 255).astype(np.uint8)
            depth_viz = cv2.applyColorMap(depth_viz, cv2.COLORMAP_JET)
            depth_viz[depth_data == 0] = [0, 0, 0]
            depth_small = cv2.resize(depth_viz, (160, 120))
            out[FRAME_HEIGHT - 120:FRAME_HEIGHT,
                FRAME_WIDTH - 160:FRAME_WIDTH] = depth_small

            # Status
            cam_z = 0.0
            T = T_base_d435cam()
            if T is not None:
                cam_z = float(T[2, 3])
            cv2.putText(out, f"D435 | {len(tracks)} targets | camZ={cam_z:.2f}m",
                        (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)

            # Encode JPEG for MJPEG stream (stdout)
            _, jpg = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            with jpeg_lock:
                jpeg_bytes = jpg.tobytes()

            # Write MJPEG frame to stdout
            sys.stdout.buffer.write(
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
            )
            sys.stdout.buffer.flush()

        except Exception:
            traceback.print_exc(file=sys.stderr)
            time.sleep(0.1)

    pipeline.stop()


# ── Main loop: read stdin commands ───────────────────────────
def main() -> None:
    global T_flange_d435cam
    global calibration_validated, calibration_reasons
    global latest_arm_pos, latest_arm_euler, latest_arm_ts

    # Load calibration
    if os.path.exists(CALIB_FILE):
        try:
            with open(CALIB_FILE) as f:
                data = json.load(f)
                audit = audit_handeye_calibration(data, "T_flange_d435cam")
                T_flange_d435cam = audit.transform
                calibration_validated = audit.calibration.validated
                calibration_reasons = audit.reasons
                emit("camera_status",
                     calibration_loaded=True,
                     calibration_validated=calibration_validated,
                     calibration_reasons=list(calibration_reasons),
                     calib_pairs=data.get("pairs", "?"),
                     calib_file=CALIB_FILE,
                )
        except Exception as e:
            emit("camera_error", message=f"Failed to load calibration: {e}")
    else:
        emit("camera_error", message=f"Calibration file not found: {CALIB_FILE}")

    # Start D435 capture thread
    cap_thread = threading.Thread(target=capture_loop, daemon=True)
    cap_thread.start()

    emit("bridge_ready", source="camera_bridge")

    # Read commands from stdin
    for line in sys.stdin:
        if shutdown_flag.is_set():
            break
        try:
            command = json.loads(line)
        except json.JSONDecodeError:
            continue

        cmd_type = command.get("type") or command.get("cmd")

        if cmd_type == "arm_state":
            # Update arm pose for coordinate transforms
            pos = command.get("tcp_position_m") or command.get("position")
            euler = command.get("tcp_euler_rad") or command.get("euler")
            if pos is not None and euler is not None:
                with arm_lock:
                    latest_arm_pos = [float(v) for v in pos]
                    latest_arm_euler = [float(v) for v in euler]
                    latest_arm_ts = time.monotonic()

        elif cmd_type == "shutdown":
            shutdown_flag.set()
            break

        elif cmd_type == "get_status":
            emit("camera_status",
                 d435_ready=FX is not None,
                 calibration_loaded=not np.array_equal(T_flange_d435cam, np.eye(4)),
                 calibration_validated=calibration_validated,
                 calibration_reasons=list(calibration_reasons),
                 resolution=f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
            )

        else:
            # Unknown command, ignore
            pass

    shutdown_flag.set()
    cap_thread.join(timeout=3.0)


if __name__ == "__main__":
    main()
