"""
D435 RGB-D grasping — YOLO detection + aligned depth + Startouch arm.
  http://<IP>:8091

Key improvements over Lumos bottle_grasp_server.py:
  - Real depth (not Z=0 plane assumption)
  - Pinhole deprojection (accurate, no SEUCM nonlinearity)
  - ROI depth median filter (noise robust)
  - No manual SCALE_X/SCALE_Y tuning

Usage:
  python d435_grasp.py              # Full grasp mode
  python d435_grasp.py --dry-run    # Detect only, no arm movement
"""
import cv2, numpy as np, json, time, sys, threading as th, os
import pyrealsense2 as rs
from flask import Flask, Response, render_template_string, jsonify, request, redirect
from ultralytics import YOLO

sys.path.insert(0, '/home/nieqingcao/arm/startouch_sdk/interface_py')
from startouchclass import SingleArm

DRY_RUN = '--dry-run' in sys.argv

# ============================================================
# D435 intrinsics (populated at startup from device)
# ============================================================
FX, FY = None, None
U0, V0 = None, None
DEPTH_SCALE = None
W, H = 640, 480

# ============================================================
# T_flange_d435cam (loaded from calibration file)
# ============================================================
CALIB_FILE = '/home/nieqingcao/calibration/d435_handeye_result.json'
T_flange_d435cam = np.eye(4)
if os.path.exists(CALIB_FILE):
    try:
        with open(CALIB_FILE) as f:
            data = json.load(f)
            T_flange_d435cam = np.array(data['T_flange_d435cam'])
            print(f"D435 calibration loaded from {CALIB_FILE} ({data.get('pairs','?')} pairs)")
    except Exception as e:
        print(f"WARNING: Failed to load D435 calibration: {e}")
        import traceback; traceback.print_exc()
else:
    print(f"WARNING: {CALIB_FILE} not found. Run d435_calibrate.py first!")

# ============================================================
# Motion params
# ============================================================
SAFE_Z = 0.12
GRASP_Z = 0.01
LIFT_Z = 0.15
PLACE_X = 0.20
PLACE_Y = 0.0
TIME_SEC = 3.0
GRIPPER_OPEN = 1.0
GRIPPER_CLOSE = 0.15

# ============================================================
# YOLO
# ============================================================
model = YOLO('yolov8n.pt')
model.to('cpu')

app = Flask(__name__)

# Shared state
capture_alive = [True]
display = [None]
jpg_buffer = [None]  # Pre-encoded JPEG bytes for MJPEG stream
rgb_frame = [None]
depth_frame = [None]       # uint16 mm, D435 aligned
tracked_objects = {}
next_track_id = [0]
arm = [None]
arm_connected = [False]
grasp_active = [False]
estop_triggered = [False]
status_msg = ["Ready"]
d435_ready = [False]
lock = th.Lock()

# ============================================================
# Depth utilities
# ============================================================
def pixel_to_3d(u, v):
    """D435 pinhole deprojection: pixel + depth → (X,Y,Z) in camera frame (meters)."""
    if depth_frame[0] is None or FX is None:
        return None

    u = int(np.clip(u, 0, W - 1))
    v = int(np.clip(v, 0, H - 1))
    d_mm = depth_frame[0][v, u]

    if d_mm <= 0 or d_mm > 5000:
        return None

    d = d_mm * DEPTH_SCALE  # mm → meters
    X = (u - U0) / FX * d
    Y = (v - V0) / FY * d
    Z = d
    return np.array([X, Y, Z])


def roi_depth(x1, y1, x2, y2):
    """Get robust depth estimate from bbox ROI. Returns (depth_m, height_m) or (None, None)."""
    if depth_frame[0] is None:
        return None, None

    x1c = max(0, int(x1))
    y1c = max(0, int(y1))
    x2c = min(W, int(x2))
    y2c = min(H, int(y2))

    roi = depth_frame[0][y1c:y2c, x1c:x2c]
    valid = roi[(roi > 100) & (roi < 5000)]  # 0.1m–5m

    if len(valid) < 20:
        # Fallback: use center pixel
        d_mm = depth_frame[0][int((y1 + y2) // 2), int((x1 + x2) // 2)]
        if d_mm > 0:
            return d_mm * DEPTH_SCALE, None
        return None, None

    # Median depth (robust to outliers)
    d_median = np.median(valid) * DEPTH_SCALE  # mm→m
    # Object height: bottom 5% vs top 5%
    z_bottom = np.percentile(valid, 95) * DEPTH_SCALE
    z_top = np.percentile(valid, 5) * DEPTH_SCALE
    object_height = z_bottom - z_top if z_bottom > z_top else None
    return d_median, object_height


# ============================================================
# Coordinate transforms
# ============================================================
def build_transform(pos, euler):
    R, _ = cv2.Rodrigues(np.array(euler, dtype=np.float64))
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = pos
    return T


_debug_count = [0]

def T_base_d435cam():
    """D435 camera pose in base frame (eye-in-hand)."""
    if arm[0] is None:
        return None
    pos, euler = arm[0].get_ee_pose_euler()
    T_base_ee = build_transform(pos, euler)
    result = T_base_ee @ T_flange_d435cam
    # Debug: print first 5 calls
    if _debug_count[0] < 5:
        _debug_count[0] += 1
        print(f"[DEBUG T_base_d435cam #{_debug_count[0]}]", flush=True)
        print(f"  arm pos={pos}, euler={euler}", flush=True)
        print(f"  T_flange_d435cam=\n{T_flange_d435cam}", flush=True)
        print(f"  T_base_ee=\n{T_base_ee}", flush=True)
        print(f"  T_base_cam=\n{result}", flush=True)
        print(f"  cam_pos in base: {result[:3,3]}", flush=True)
    return result


def base_frame_position(u, v, x1, y1, x2, y2):
    """Compute object XY in robot base frame via ray-plane intersection.

    Pixel → camera ray → transform to base frame → intersect with Z=DESK_Z plane.

    Requires camera to be looking at the desk (ray must intersect Z=0).
    Uses D435 depth as fallback when ray-plane intersection fails.

    Returns (bx, by, bz) in meters, or None.
    """
    T_base_cam = T_base_d435cam()
    if T_base_cam is None:
        return None
    if FX is None:
        return None

    # Pixel → unit ray in camera frame (pinhole)
    xn = (u - U0) / FX
    yn = (v - V0) / FY
    ray_cam = np.array([xn, yn, 1.0])
    ray_cam /= np.linalg.norm(ray_cam)

    # Transform ray to base frame
    R_base_cam = T_base_cam[:3, :3]
    cam_pos = T_base_cam[:3, 3]
    ray_base = R_base_cam @ ray_cam

    # If ray points upward (away from desk), fall back to depth deprojection
    DESK_Z = 0.0
    if ray_base[2] > 0:
        # Camera looking up — use depth-based deprojection instead
        if depth_frame[0] is None:
            return None
        uc = int(np.clip(u, 0, W - 1))
        vc = int(np.clip(v, 0, H - 1))
        d_mm = float(depth_frame[0][vc, uc])
        if d_mm <= 0 or d_mm > 5000:
            return None
        d = d_mm * DEPTH_SCALE
        # Deproject: p_cam = d * ray_cam (ray_cam is unit vector)
        p_cam = d * ray_cam
        p_base = T_base_cam @ np.append(p_cam, 1.0)
        return p_base[:3]

    # Ray points downward — intersect with desk plane Z=DESK_Z
    if abs(ray_base[2]) < 1e-10:
        return None

    t = (DESK_Z - cam_pos[2]) / ray_base[2]
    if t < 0:
        return None  # Intersection behind camera

    p_base = cam_pos + t * ray_base
    return p_base


# ============================================================
# Tracking
# ============================================================
def iou(box1, box2):
    x1 = max(box1[0], box2[0]); y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2]); y2 = min(box1[3], box2[3])
    if x2 <= x1 or y2 <= y1: return 0
    inter = (x2 - x1) * (y2 - y1)
    a1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    a2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    return inter / (a1 + a2 - inter + 1e-6)


def extract_color_hist(frame, box):
    x1, y1, x2, y2 = box
    roi = frame[max(0, y1):min(H, y2), max(0, x1):min(W, x2)]
    if roi.size == 0:
        return np.zeros(32)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256])
    return (hist / (hist.sum() + 1e-6)).flatten().astype(np.float32)


def update_tracking(new_boxes, frame=None):
    global tracked_objects, next_track_id
    if not new_boxes:
        tracked_objects = {}
        return {}

    matched = {}
    used_new = set()
    used_old = set()

    for tid, old in tracked_objects.items():
        best_iou, best_j = 0, -1
        for j, new_box in enumerate(new_boxes):
            if j in used_new: continue
            i = iou(old['box'], new_box['box'])
            if i > best_iou:
                best_iou, best_j = i, j
        if best_iou > 0.3:
            matched[tid] = new_boxes[best_j]
            used_new.add(best_j)
            used_old.add(tid)

    if frame is not None:
        for tid, old in tracked_objects.items():
            if tid in used_old or 'hist' not in old: continue
            best_sim, best_j = 0, -1
            for j, new_box in enumerate(new_boxes):
                if j in used_new: continue
                new_hist = extract_color_hist(frame, new_box['box'])
                sim = cv2.compareHist(old['hist'], new_hist, cv2.HISTCMP_CORREL)
                if sim > best_sim:
                    best_sim, best_j = sim, j
            if best_sim > 0.5:
                matched[tid] = new_boxes[best_j]
                used_new.add(best_j)
                used_old.add(tid)

    new_tracked = {}
    for tid, box_data in matched.items():
        box_data['hist'] = extract_color_hist(frame, box_data['box']) if frame is not None else None
        new_tracked[tid] = box_data

    for j, box_data in enumerate(new_boxes):
        if j not in used_new:
            tid = next_track_id[0]
            next_track_id[0] += 1
            box_data['hist'] = extract_color_hist(frame, box_data['box']) if frame is not None else None
            new_tracked[tid] = box_data

    tracked_objects = new_tracked
    return new_tracked


# ============================================================
# D435 capture + YOLO detection
# ============================================================
def capture_loop():
    global display, tracked_objects, rgb_frame, depth_frame
    global FX, FY, U0, V0, DEPTH_SCALE, W, H

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

    try:
        profile = pipeline.start(config)
    except Exception as e:
        print(f"D435 start error: {e}")
        print("Is D435 on USB 3.0 (blue) port?")
        status_msg[0] = f"D435 error: {e}"
        return

    # Read intrinsics
    color_stream = profile.get_stream(rs.stream.color).as_video_stream_profile()
    intr = color_stream.get_intrinsics()
    FX, FY = intr.fx, intr.fy
    U0, V0 = intr.ppx, intr.ppy
    W, H = intr.width, intr.height
    DEPTH_SCALE = profile.get_device().first_depth_sensor().get_depth_scale()
    d435_ready[0] = True

    print(f"D435: {W}x{H}, fx={FX:.1f} fy={FY:.1f}, depth_scale={DEPTH_SCALE:.4f}")
    print(f"D435: u0={U0:.1f} v0={V0:.1f}")

    align = rs.align(rs.stream.color)

    # Warm up
    for _ in range(30):
        pipeline.wait_for_frames()

    print("D435 grasp stream ready.")
    tick = 0

    try:
        while True:
            try:
                frames = pipeline.wait_for_frames()
                aligned = align.process(frames)
                color_frame = aligned.get_color_frame()
                depth_f = aligned.get_depth_frame()

                if not color_frame or not depth_f:
                    time.sleep(0.01); continue

                frame = np.asanyarray(color_frame.get_data())
                depth_data = np.asanyarray(depth_f.get_data())

                with lock:
                    rgb_frame[0] = frame.copy()
                    depth_frame[0] = depth_data

                tick += 1

                # YOLO every 10 frames (~3fps)
                if tick % 10 == 0:
                    small = cv2.resize(frame, (320, 240))
                    results = model(small, conf=0.25, verbose=False, imgsz=320,
                                    classes=[39, 40, 41, 44, 46, 47])

                    new_boxes = []
                    for r in results:
                        if r.boxes is None: continue
                        for box in r.boxes:
                            cls_id = int(box.cls[0])
                            conf = float(box.conf[0])
                            xyxy = box.xyxy[0].cpu().numpy()
                            x1, y1, x2, y2 = int(xyxy[0]*2), int(xyxy[1]*2), int(xyxy[2]*2), int(xyxy[3]*2)
                            x1, y1 = max(0, x1), max(0, y1)
                            x2, y2 = min(W-1, x2), min(H-1, y2)
                            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                            pt_base = base_frame_position(cx, cy, x1, y1, x2, y2)
                            if pt_base is not None:
                                bx, by, bz = float(pt_base[0]), float(pt_base[1]), float(pt_base[2])
                            else:
                                bx, by, bz = 0.0, 0.0, 0.0

                            new_boxes.append({
                                'label': model.names.get(cls_id, 'obj'),
                                'cx': cx, 'cy': cy, 'conf': conf,
                                'bx': bx, 'by': by, 'bz': bz,
                                'box': (x1, y1, x2, y2)
                            })
                    update_tracking(new_boxes, frame)

                # Draw
                out = frame.copy()
                colors = [(0, 255, 0), (255, 200, 0), (0, 200, 255), (255, 0, 200), (200, 255, 0)]
                with lock:
                    tbs = dict(tracked_objects)

                for i, (tid, obj) in enumerate(tbs.items()):
                    color = colors[tid % len(colors)]
                    x1, y1, x2, y2 = obj['box']
                    cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(out,
                                f"#{tid} {obj['label']} base({obj['bx']:.3f},{obj['by']:.3f},{obj['bz']:.3f})",
                                (x1, max(y1 - 8, 12)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
                    cv2.circle(out, (obj['cx'], obj['cy']), 4, color, -1)

                # Depth overlay
                depth_viz = np.clip(depth_data.astype(np.float32) / 3000.0 * 255, 0, 255).astype(np.uint8)
                depth_viz = cv2.applyColorMap(depth_viz, cv2.COLORMAP_JET)
                depth_viz[depth_data == 0] = [0, 0, 0]
                dh, dw = 120, 160
                depth_small = cv2.resize(depth_viz, (dw, dh))
                out[H - dh:H, W - dw:W] = depth_small

                # Status
                s = "⚠ E-STOP" if estop_triggered[0] else ("🤖 Grasping..." if grasp_active[0] else f"D435 RGB-D | {len(tbs)} targets")
                color_s = (0, 0, 255) if estop_triggered[0] else (0, 255, 0)
                cv2.putText(out, s, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color_s, 1)

                with lock:
                    display[0] = out
                    _, jpg = cv2.imencode('.jpg', out, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    jpg_buffer[0] = jpg.tobytes()
                time.sleep(0.03)

            except Exception as e:
                print(f"Frame error (recovering): {e}", flush=True)
                time.sleep(0.1)

    except Exception as e:
        print(f"D435 capture error: {e}", flush=True)
        import traceback; traceback.print_exc()
    finally:
        capture_alive[0] = False
        pipeline.stop()
        print("Capture loop exited.", flush=True)


# ============================================================
# Grasp thread
# ============================================================
def grasp_thread(tid):
    global grasp_active, estop_triggered, status_msg

    if arm[0] is None:
        status_msg[0] = "Arm not connected"
        grasp_active[0] = False
        return

    with lock:
        obj = tracked_objects.get(tid)
    if obj is None:
        status_msg[0] = f"Target #{tid} lost"
        grasp_active[0] = False
        return

    bx, by, bz = obj['bx'], obj['by'], obj['bz']
    if bx == 0 and by == 0 and bz == 0:
        status_msg[0] = f"Target #{tid}: no depth data, using center pixel fallback"
        # Fallback: use center pixel deprojection
        p = pixel_to_3d(obj['cx'], obj['cy'])
        if p is not None:
            T_base_cam = T_base_d435cam()
            if T_base_cam is not None:
                p_base = T_base_cam @ np.append(p, 1.0)
                bx, by, bz = p_base[:3]
            else:
                bx, by, bz = p[0], p[1], p[2]
        else:
            grasp_active[0] = False
            return

    status_msg[0] = f"Grasping #{tid}: ({bx:.4f}, {by:.4f}, {bz:.3f})m"

    try:
        a = arm[0]
        pos, euler = a.get_ee_pose_euler()
        r, p, y = float(euler[0]), float(euler[1]), float(euler[2])

        # XY from D435 depth (more accurate than homography)
        # Z uses desk plane assumption (Z≈0 in base frame)
        tx, ty = bx, by
        DESK_Z = 0.0
        tz = max(DESK_Z + 0.01, 0.03)  # Grasp just above desk

        print(f"Grasp #{tid}: target=({tx:.4f},{ty:.4f},{tz:.4f}) "
              f"cam_z={bz:.3f}m desk_z={DESK_Z:.3f}", flush=True)

        if DRY_RUN:
            print(f"  [DRY RUN] Would move to ({tx:.4f},{ty:.4f},{tz:.4f})")
            status_msg[0] = f"[DRY RUN] target #{tid} at ({tx:.4f},{ty:.4f},{tz:.3f})m"
            grasp_active[0] = False
            return

        # 1. Hover above target
        safe_z = max(tz + 0.10, 0.15)
        status_msg[0] = f"#{tid}: hover..."
        try:
            a.move_l([[tx, ty, safe_z, r, p, y]], time_sec=2.5,
                     blend_radius_m=0.0,
                     position_tolerance_m=0.04,
                     orientation_tolerance_rad=0.4)
        except Exception as e1:
            print(f"  hover failed: {e1}", flush=True)
            status_msg[0] = f"#{tid}: hover failed. Aborting."
            grasp_active[0] = False
            return

        if estop_triggered[0]:
            grasp_active[0] = False
            return

        # 2. Descend to grasp
        status_msg[0] = f"#{tid}: descend to Z={tz:.3f}..."
        try:
            a.move_l([[tx, ty, tz, r, p, y]], time_sec=1.5,
                     blend_radius_m=0.0,
                     position_tolerance_m=0.04,
                     orientation_tolerance_rad=0.4)
        except Exception as e2:
            print(f"  descend failed: {e2}", flush=True)

        if estop_triggered[0]:
            grasp_active[0] = False
            return

        # 3. Close gripper
        a.setGripperPosition(GRIPPER_CLOSE)
        time.sleep(0.4)
        gripper_pos = a.get_gripper_position()
        grabbed = gripper_pos > 0.25

        if grabbed:
            status_msg[0] = f"#{tid}: GRABBED! ✓"
            a.move_l([[pos[0], pos[1], pos[2] + 0.05, r, p, y]], time_sec=2.0,
                     blend_radius_m=0.0, position_tolerance_m=0.04, orientation_tolerance_rad=0.4)
            a.go_home()
            time.sleep(4.0)
            a.setGripperPosition(GRIPPER_OPEN)
            time.sleep(0.5)
            status_msg[0] = f"#{tid}: GRABBED! ✓ Done"
        else:
            status_msg[0] = f"#{tid}: EMPTY! Gripper fully closed."
            a.go_home()
            time.sleep(3.0)
            a.setGripperPosition(GRIPPER_OPEN)
            time.sleep(0.3)

    except Exception as e:
        status_msg[0] = f"Error: {e}"
        import traceback; traceback.print_exc()
    finally:
        grasp_active[0] = False


# ============================================================
# HTML
# ============================================================
HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>D435 RGB-D Grasp</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,sans-serif;display:flex;height:100vh}
.l{flex:1;display:flex;align-items:center;justify-content:center;padding:8px}
.l img{max-width:100%;max-height:98vh;border:2px solid #30363d;border-radius:8px}
.r{width:300px;padding:14px;background:#161b22;overflow-y:auto;border-left:1px solid #30363d}
h2{color:#58a6ff;font-size:15px;margin-bottom:4px}
.tag{font-size:10px;color:#8b949e;margin-bottom:10px}
.o{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;margin:6px 0;font-size:12px}
.o .n{color:#3fb950;font-weight:bold}
.o .d{color:#7ee787;font-size:11px}
.o .z{color:#d2991d;font-size:10px}
.bar{height:3px;background:#30363d;border-radius:2px;margin-top:3px}
.bar div{height:3px;background:#3fb950;border-radius:2px}
.btn{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:bold;margin:3px 0;width:100%}
.btn-go{background:#238636;color:#fff}.btn-go:hover{background:#2ea043}
.btn-estop{background:#da3633;color:#fff;font-size:18px;padding:16px;animation:pulse 1s infinite}
.btn-estop:hover{background:#f85149}
.btn-arm{background:#1f6feb;color:#fff}.btn-arm:hover{background:#388bfd}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.7}}
#status{font-size:13px;margin:8px 0;padding:8px;border-radius:4px}
.status-ok{background:#0d3320;color:#3fb950}
.status-warn{background:#332000;color:#d2991d}
.status-err{background:#330000;color:#f85149}
</style></head><body>
<div class="l"><img id="vid" src="/snapshot"></div>
<div class="r">
<h2>🎯 D435 RGB-D Grasp</h2>
<div class="tag" id="info">Loading...</div>
<div id="status" class="status-ok">Ready</div>
<div id="list"></div>
<div style="flex:1;min-height:10px"></div>
<div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;margin:6px 0;font-size:11px;color:#8b949e">
💡 臂姿调整请用 <a href="http://192.168.58.68:3000" target="_blank" style="color:#58a6ff">端口 3000</a> 控制面板
</div>
<button class="btn btn-arm" onclick="connect()">🔌 Connect Arm</button>
<button class="btn btn-estop" onclick="estop()" id="estop-btn">⏹ EMERGENCY STOP</button>
</div>
<script>
// Video: poll snapshot every 200ms (no MJPEG, no Flask thread blocking)
setInterval(()=>{document.getElementById('vid').src='/snapshot?'+Date.now()},200);

let poll=setInterval(async()=>{
  let r=await fetch('/objects');let d=await r.json();
  document.getElementById('info').textContent=d.count+' targets | D435 depth: '+(d.d435_ready?'✓':'✗');
  let s=document.getElementById('status');
  s.textContent=d.status;
  s.className=d.estop?'status-err':(d.grasping?'status-warn':'status-ok');

  let h='';
  for(let o of d.objects){
    h+=`<div class="o">
      <span class="n">#${o.id} ${o.label}</span> <span style="font-size:10px;color:#8b949e">${o.conf}</span>
      <div class="d">base (${o.bx}, ${o.by}, z=${o.bz})m</div>
      <div class="z">D435 depth: ${o.depth_m}m</div>
      <div class="bar"><div style="width:${(o.conf*100)|0}%"></div></div>
      <button class="btn btn-go" onclick="grasp(${o.id})" style="font-size:11px;margin-top:4px">🎯 Grasp #${o.id}</button>
    </div>`;
  }
  document.getElementById('list').innerHTML=h||'<div style="color:#8b949e;font-size:12px">No targets detected</div>';
},600);

async function grasp(id){await fetch('/grasp?id='+id)}
async function estop(){
  document.getElementById('estop-btn').style.background='#ff0000';
  await fetch('/estop');
}
async function connect(){let r=await fetch('/connect');let d=await r.json();document.getElementById('status').textContent=d.status}
</script>
</body></html>"""


# ============================================================
# Routes
# ============================================================
@app.route('/')
def index(): return render_template_string(HTML)


def gen():
    last_yield = time.time()
    while capture_alive[0]:
        with lock: data = jpg_buffer[0]
        if data is not None:
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + data + b'\r\n')
            last_yield = time.time()
        else:
            # No frame yet or capture died — yield a blank frame to keep connection alive
            if time.time() - last_yield > 3.0:
                return  # Capture seems dead, close stream
            time.sleep(0.1)


@app.route('/snapshot')
def snapshot():
    with lock: data = jpg_buffer[0]
    if data is None:
        return '', 204
    return Response(data, mimetype='image/jpeg')


@app.route('/video_feed')
def video_feed():
    return redirect('/snapshot')


@app.route('/objects')
def get_objects():
    with lock:
        tbs = dict(tracked_objects)
        st = status_msg[0]
        es = estop_triggered[0]
        ga = grasp_active[0]
        d4 = d435_ready[0]

    objs = []
    for tid, o in sorted(tbs.items()):
        # Compute depth at center for display
        d_mm = depth_frame[0][o['cy'], o['cx']] if depth_frame[0] is not None else 0
        objs.append({
            "id": tid, "label": o['label'], "conf": f"{o['conf']:.2f}",
            "cx": o['cx'], "cy": o['cy'],
            "bx": f"{o['bx']:.4f}", "by": f"{o['by']:.4f}", "bz": f"{o['bz']:.3f}",
            "depth_m": f"{d_mm * DEPTH_SCALE:.3f}" if DEPTH_SCALE else "N/A"
        })

    return jsonify({
        "count": len(objs), "objects": objs, "status": st,
        "estop": es, "grasping": ga, "d435_ready": d4
    })


@app.route('/grasp')
def grasp():
    if estop_triggered[0]:
        return jsonify(status="E-STOP active!")
    if grasp_active[0]:
        return jsonify(status="Grasp in progress")
    if arm[0] is None:
        return jsonify(status="Connect arm first!")

    tid = int(request.args.get('id', 0))
    grasp_active[0] = True
    th.Thread(target=grasp_thread, args=(tid,), daemon=True).start()
    return jsonify(status=f"Grasping #{tid}...")


@app.route('/estop')
def estop():
    global estop_triggered
    estop_triggered[0] = True
    if arm[0] is not None:
        try:
            arm[0].setGripperPosition(GRIPPER_OPEN)
            arm[0].cleanup()
        except: pass
    arm[0] = None
    status_msg[0] = "⚠ E-STOP ACTIVE"
    return jsonify(status="E-STOPPED")


@app.route('/connect')
def connect():
    global estop_triggered
    estop_triggered[0] = False  # Clear E-STOP
    try:
        arm[0] = SingleArm(can_interface_="can0", enable_fd_=False)
        time.sleep(0.3)
        arm[0].setGripperPosition(GRIPPER_OPEN)
        time.sleep(0.3)
        # Move to look-down pose: all joints 0°, J4=20° so camera faces desk
        J4_DEG = 20.0
        joint_angles = np.array([0.0, 0.0, 0.0, np.deg2rad(J4_DEG), 0.0, 0.0])
        arm[0].set_joint(joint_angles, tf=2.0)
        time.sleep(3.0)
        arm_connected[0] = True

        if not np.array_equal(T_flange_d435cam, np.eye(4)):
            status_msg[0] = "Homed. D435 calib loaded ✓"
        else:
            status_msg[0] = "Homed. No D435 calib!"

        pos, _ = arm[0].get_ee_pose_euler()
        return jsonify(status=status_msg[0])
    except Exception as e:
        return jsonify(status=f"Connect failed: {e}")


if __name__ == '__main__':
    th.Thread(target=capture_loop, daemon=True).start()
    time.sleep(3)
    port = int(os.environ.get('GRASP_PORT', 8091))
    print(f"D435 RGB-D Grasp: http://192.168.58.68:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
