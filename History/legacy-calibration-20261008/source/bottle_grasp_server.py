"""
Multi-bottle tracking + grasp + E-STOP.
  http://<IP>:8088
"""
import cv2, numpy as np, json, time, sys, threading as th, os
from flask import Flask, Response, render_template_string, jsonify, request
from ultralytics import YOLO

sys.path.insert(0, '/home/nieqingcao/arm/startouch_sdk/interface_py')
from startouchclass import SingleArm

# ============================================================
# Eye-in-hand: camera on robot flange, moves with arm.
# T_flange_camera: camera pose in flange frame (approximate!)
# Camera looks forward-down from flange
# ============================================================
# Calibrated 2026-07-30, 14 pairs, Tsai method
T_flange_camera = np.array([
    [0.989535, 0.143550, -0.014641, 0.173193],
    [-0.137395, 0.968354, 0.208359, -0.157537],
    [0.044088, -0.204167, 0.977943, -0.228590],
    [0.000000, 0.000000, 0.000000, 1.000000]
])

# SEUCM intrinsics
FX, FY = 392.168, 392.168
U0, V0 = 637.761, 640.597
ALPHA, BETA = 0.678979, 0.749026

def unproject(u, v):
    """Pixel → unit direction in camera frame (SEUCM)."""
    xn = (u - U0) / FX
    yn = (v - V0) / FY
    r2 = xn*xn + yn*yn
    a2, a2b = ALPHA*ALPHA, ALPHA*ALPHA - BETA
    if a2b > 0 and r2 >= 1.0/a2b: return None
    sq = np.sqrt(max(1 - a2b*r2, 0))
    denom = ALPHA*sq + (1-ALPHA)
    if denom < 1e-10: return None
    Z = (1 - a2*BETA*r2) / denom
    norm = np.sqrt(xn*xn + yn*yn + Z*Z)
    if norm < 1e-10: return None
    return np.array([xn/norm, yn/norm, Z/norm])

def pixel_to_base(u, v):
    """Pixel → base XY via Charuco homography. Simple and calibrated."""
    with open('/home/nieqingcao/calibration/desktop_calib_result.json') as f:
        H = np.array(json.load(f)['H'])
    p = np.array([u, v, 1.0])
    w = H @ p
    wx, wy = float(w[0]/w[2]), float(w[1]/w[2])
    return np.array([wx, wy, 0.0])  # Z=0 desk plane

# ============================================================
# Charuco board detection (for desk reference frame)
# ============================================================
SX, SY = 9, 12
SL, ML = 0.015, 0.01125
aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
charuco_board = cv2.aruco.CharucoBoard((SX, SY), SL, ML, aruco_dict)
board_obj, board_ids = charuco_board.getObjPoints(), charuco_board.getIds()
board_id_set = set(board_ids.flatten())
detector_params = cv2.aruco.DetectorParameters()

# Pinhole-approx K for PnP (same as handeye_calib.py)
K_PNP = np.array([[392.168, 0, 637.761],
                  [0, 392.168, 640.597],
                  [0, 0, 1]], dtype=np.float64)
DIST_ZERO = np.zeros(4)

# Tool offset from robot_kinematics.yaml: EE = flange + translate(0.17334, 0, 0)
TOOL_OFFSET = np.array([0.17334, 0.0, 0.0])

def detect_board_pose(gray, K=None):
    """Detect Charuco board, return (rvec, tvec) = T_camera_board, or (None, None)."""
    if K is None:
        K = K_PNP
    ad = cv2.aruco.ArucoDetector(aruco_dict, detector_params)
    mc, mi, _ = ad.detectMarkers(gray)
    if mi is None or len(mi) < 6:
        return None, None, mc, mi

    valid = [int(m) in board_id_set for m in mi.flatten()]
    mc_v = [mc[i] for i in range(len(mc)) if valid[i]]
    mi_v = np.array([mi.flatten()[i] for i in range(len(mi)) if valid[i]])

    if len(mi_v) < 6:
        return None, None, mc, mi

    half = ML / 2
    offsets = [(-half,-half),(half,-half),(half,half),(-half,half)]
    obj_pts, img_pts = [], []

    for corners, mid in zip(mc_v, mi_v):
        mid_val = int(mid)
        idx = np.where(board_ids.flatten() == mid_val)[0]
        if len(idx) == 0: continue
        obj_c = board_obj[idx[0]].flatten()
        for j, (dx, dy) in enumerate(offsets):
            obj_pts.append([obj_c[0]+dx, obj_c[1]+dy, 0.0])
            img_pts.append(corners[0][j])

    if len(obj_pts) < 8:
        return None, None, mc, mi

    obj_pts = np.array(obj_pts, dtype=np.float64).reshape(-1, 3)
    img_pts = np.array(img_pts, dtype=np.float64).reshape(-1, 2)
    ok, rvec, tvec = cv2.solvePnP(obj_pts, img_pts, K, DIST_ZERO,
                                   flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        return None, None, mc, mi
    # Scale tvec back to full-res if using downscaled image
    return rvec, tvec, mc, mi

def build_transform(pos, euler):
    """Create 4x4 transform from position + Euler angles."""
    R, _ = cv2.Rodrigues(np.array(euler, dtype=np.float64))
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = pos
    return T

def inv_transform(T):
    """Invert 4x4 homogeneous transform."""
    Ti = np.eye(4)
    R = T[:3, :3]; t = T[:3, 3]
    Ti[:3, :3] = R.T
    Ti[:3, 3] = -R.T @ t
    return Ti

# ============================================================
# Desk calibration state
# ============================================================
T_base_board = [None]  # 4x4, board→base transform
desk_calibrated = [False]
DESK_REF_FILE = '/home/nieqingcao/calibration/desk_ref.json'
Z_DESK = 0.0                           # Desk height in base frame
T_base_camera_home = [None]             # Camera pose at home (cached)

# Motion params
SAFE_Z = 0.12; GRASP_Z = 0.01; LIFT_Z = 0.15
PLACE_X = 0.20; PLACE_Y = 0.0
TIME_SEC = 3.0

# ============================================================
model = YOLO('yolov8n.pt'); model.to('cpu')
app = Flask(__name__)

# Shared state
display = [None]
rgb_frame = [None]      # Full-res frame for Charuco detection
board_detection = [None]  # Latest board detection: (rvec, tvec, n_markers) or None
tracked_bottles = {}
next_track_id = [0]
lock = th.Lock()
arm = [None]           # SingleArm instance
grasp_active = [False]
estop_triggered = [False]
status_msg = ["Ready"]
locked_track_id = [None]  # Locked bottle ID for stable tracking
GRIPPER_OPEN = 1.0    # Use setGripperPosition (0-1 range)
GRIPPER_CLOSE = 0.15  # ~15% closed for grasping
SCALE_X = [0.0006]    # Runtime-tunable pixel→base scale (dv→X)
SCALE_Y = [0.0004]    # Runtime-tunable pixel→base scale (du→Y)

# ============================================================
# Tracking
# ============================================================
def iou(box1, box2):
    x1 = max(box1[0], box2[0]); y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2]); y2 = min(box1[3], box2[3])
    if x2 <= x1 or y2 <= y1: return 0
    inter = (x2-x1)*(y2-y1)
    a1 = (box1[2]-box1[0])*(box1[3]-box1[1])
    a2 = (box2[2]-box2[0])*(box2[3]-box2[1])
    return inter / (a1 + a2 - inter + 1e-6)

def extract_color_hist(frame, box):
    """Extract HSV color histogram from bottle ROI for appearance matching."""
    x1, y1, x2, y2 = box
    roi = frame[max(0,y1):min(frame.shape[0],y2), max(0,x1):min(frame.shape[1],x2)]
    if roi.size == 0:
        return np.zeros(32)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256])
    hist = hist.flatten() / (hist.sum() + 1e-6)
    return hist.astype(np.float32)

def update_tracking(new_boxes, frame=None):
    """IoU + color-histogram multi-object tracking."""
    global tracked_bottles, next_track_id
    if not new_boxes:
        tracked_bottles = {}
        return {}

    matched = {}
    used_new = set()
    used_old = set()

    # Stage 1: IoU matching
    for tid, old in tracked_bottles.items():
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

    # Stage 2: Color histogram matching for lost tracks
    if frame is not None:
        for tid, old in tracked_bottles.items():
            if tid in used_old: continue
            if 'hist' not in old: continue
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

    # Build new tracked set
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

    tracked_bottles = new_tracked
    return new_tracked

# ============================================================
# Camera capture
# ============================================================
def capture_loop():
    global display, tracked_bottles
    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YU12'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    tick = 0
    while True:
        ret, raw = cap.read()
        if not ret: time.sleep(0.01); continue
        frame = cv2.cvtColor(raw, cv2.COLOR_YUV2BGR_I420)
        tick += 1

        # Store full-res frame (detection thread picks it up)
        with lock: rgb_frame[0] = frame.copy()

        if tick % 15 == 0:
            small = cv2.resize(frame, (640, 640))
            results = model(small, conf=0.25, verbose=False, imgsz=640, classes=[39, 40, 41, 44, 46, 47])  # bottle/cup/bowl variants
            new_boxes = []
            for r in results:
                if r.boxes is None: continue
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    xyxy = box.xyxy[0].cpu().numpy()
                    x1,y1,x2,y2 = map(int, xyxy * 2)
                    cx,cy = (x1+x2)//2, (y1+y2)//2
                    # Use homography as fallback; desk calibration overrides in grasp
                    pt_base = pixel_to_base(cx, cy)
                    bx, by, bz = pt_base[0], pt_base[1], pt_base[2]
                    new_boxes.append({
                        'label': model.names.get(cls_id, 'obj'),
                        'cx': cx, 'cy': cy, 'conf': conf,
                        'bx': bx, 'by': by, 'bz': bz,
                        'box': (x1, y1, x2, y2)
                    })
            update_tracking(new_boxes, frame)

        # Draw
        out = cv2.resize(frame, (640, 640))
        colors = [(0,255,0),(255,200,0),(0,200,255),(255,0,200),(200,255,0)]
        with lock:
            tbs = dict(tracked_bottles)
        for i, (tid, obj) in enumerate(tbs.items()):
            color = colors[tid % len(colors)]
            x1,y1,x2,y2 = obj['box']
            sx1,sy1,sx2,sy2 = x1//2,y1//2,x2//2,y2//2
            scx,scy = obj['cx']//2, obj['cy']//2
            cv2.rectangle(out, (sx1,sy1), (sx2,sy2), color, 2)
            cv2.putText(out, f"#{tid} {obj['label']} base({obj['bx']:.3f},{obj['by']:.3f},{obj['bz']:.3f})",
                        (sx1, max(sy1-6,12)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            cv2.circle(out, (scx,scy), 4, color, -1)

        status = "⚠ E-STOP" if estop_triggered[0] else ("🤖 Grasping..." if grasp_active[0] else f"Tracking {len(tbs)} targets")
        cv2.putText(out, status, (8,22), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0,0,255) if estop_triggered[0] else (0,255,0), 1)
        # Charuco board status
        bd = board_detection[0]
        bd_status = f"Board: {bd[2]} markers" if bd else "Board: detecting..."
        bd_color = (0,255,0) if (bd and bd[0] is not None) else (100,100,255)
        cv2.putText(out, bd_status, (8,42), cv2.FONT_HERSHEY_SIMPLEX, 0.4, bd_color, 1)
        with lock: display[0] = out
        time.sleep(0.03)

# ============================================================
# Arm control thread
# ============================================================
def bottle_position_in_base(obj_cx, obj_cy):
    """Compute bottle 3D position in base frame using desk calibration.
    Returns (x, y, z) in base frame, or None if not calibrated / invalid."""
    if not desk_calibrated[0] or T_base_board[0] is None:
        return None

    if arm[0] is None:
        return None

    # 1. Get current EE pose → T_base_ee
    pos_ee, euler_ee = arm[0].get_ee_pose_euler()
    T_base_ee = build_transform(pos_ee, euler_ee)

    # 2. Camera pose in base frame (T_flange_camera was calibrated using EE poses,
    #    so it's actually T_ee_camera — NO tool offset correction needed)
    T_base_camera = T_base_ee @ T_flange_camera
    R_base_camera = T_base_camera[:3, :3]
    cam_pos_base = T_base_camera[:3, 3]

    # 4. Unproject pixel to ray in camera frame (SEUCM)
    ray_cam = unproject(obj_cx, obj_cy)
    if ray_cam is None:
        return None

    # 5. Transform ray to base frame
    ray_base = R_base_camera @ ray_cam

    # 6. Intersect with desk plane (Z=0 in board frame)
    T_board_base = inv_transform(T_base_board[0])
    R_board_base = T_board_base[:3, :3]
    t_board_base = T_board_base[:3, 3]

    cam_in_board = R_board_base @ cam_pos_base + t_board_base
    ray_in_board = R_board_base @ ray_base

    if abs(ray_in_board[2]) < 1e-10:
        return None  # Ray parallel to desk

    lam = -cam_in_board[2] / ray_in_board[2]
    if lam < 0:
        return None  # Intersection behind camera

    p_board = cam_in_board + lam * ray_in_board  # Bottle position in board frame

    # 7. Transform to base frame
    p_base = T_base_board[0][:3, :3] @ p_board + T_base_board[0][:3, 3]
    return p_base


def grasp_thread(tid):
    global grasp_active, estop_triggered, status_msg
    if arm[0] is None:
        status_msg[0] = "Arm not connected"
        grasp_active[0] = False
        return

    with lock: obj = tracked_bottles.get(tid)
    if obj is None:
        status_msg[0] = f"Target #{tid} lost"
        grasp_active[0] = False
        return

    obj_cx, obj_cy = obj['cx'], obj['cy']
    status_msg[0] = f"Grasping #{tid} at pixel({obj_cx},{obj_cy})"

    try:
        a = arm[0]
        pos, euler = a.get_ee_pose_euler()
        r, p, y = float(euler[0]), float(euler[1]), float(euler[2])

        # Linear pixel-offset (SCALE tunable from web UI)
        du = obj_cx - U0
        dv = obj_cy - V0
        sx, sy = SCALE_X[0], SCALE_Y[0]
        dx = max(-0.25, min(0.25, dv * sx))
        dy = max(-0.25, min(0.25, -du * sy))
        tx = pos[0] + dx
        ty = pos[1] + dy
        tz = max(pos[2] - 0.05, 0.03)
        print(f"Grasp #{tid}: du={du:.0f} dv={dv:.0f} offset=({dx:.4f},{dy:.4f}) target=({tx:.4f},{ty:.4f},{tz:.4f})", flush=True)

        # 1. Hover: move XY at safe height (above bottle)
        status_msg[0] = f"#{tid}: hover..."
        safe_z = max(pos[2] + 0.08, 0.12)  # 8cm above current or at least 12cm
        try:
            a.move_l([[tx, ty, safe_z, r, p, y]], time_sec=2.5,
                     blend_radius_m=0.0,
                     position_tolerance_m=0.04,
                     orientation_tolerance_rad=0.4)
            print(f"  hover OK", flush=True)
        except Exception as e1:
            print(f"  hover failed: {e1}", flush=True)
            status_msg[0] = f"#{tid}: IK failed. Aborting."
            grasp_active[0] = False
            return

        if estop_triggered[0]:
            grasp_active[0] = False
            return

        # 2. Descend: straight down to grasp Z
        status_msg[0] = f"#{tid}: descend..."
        try:
            a.move_l([[tx, ty, tz, r, p, y]], time_sec=1.5,
                     blend_radius_m=0.0,
                     position_tolerance_m=0.04,
                     orientation_tolerance_rad=0.4)
            print(f"  descend OK", flush=True)
        except Exception as e2:
            print(f"  descend failed: {e2}, trying to close anyway", flush=True)

        if estop_triggered[0]:
            grasp_active[0] = False
            return

        # 3. Close gripper + check if grabbed
        a.setGripperPosition(GRIPPER_CLOSE)
        time.sleep(0.4)
        gripper_pos = a.get_gripper_position()
        grabbed = gripper_pos > 0.25

        if grabbed:
            status_msg[0] = f"#{tid}: GRABBED! ✓"
            locked_track_id[0] = None
            # Lift
            a.move_l([[pos[0], pos[1], pos[2] + 0.05, r, p, y]], time_sec=2.0,
                     blend_radius_m=0.0, position_tolerance_m=0.04, orientation_tolerance_rad=0.4)
            # Go home
            a.go_home()
            time.sleep(4.0)
            a.setGripperPosition(GRIPPER_OPEN)
            time.sleep(0.5)
            status_msg[0] = f"#{tid}: GRABBED! ✓ Done"
        else:
            status_msg[0] = f"#{tid}: EMPTY! Gripper closed fully. Adjust position."
            # Go home immediately (nothing to lift)
            a.go_home()
            time.sleep(3.0)
            a.setGripperPosition(GRIPPER_OPEN)
            time.sleep(0.3)
            status_msg[0] = f"#{tid}: EMPTY — reposition and retry"

    except Exception as e:
        status_msg[0] = f"Error: {e}"
        import traceback
        traceback.print_exc()
    finally:
        grasp_active[0] = False

# ============================================================
# HTML
# ============================================================
HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Bottle Grasp</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,sans-serif;display:flex;height:100vh}
.l{flex:1;display:flex;align-items:center;justify-content:center;padding:8px;position:relative}
.l img{max-width:100%;max-height:98vh;border:2px solid #30363d;border-radius:8px}
.r{width:300px;padding:14px;background:#161b22;overflow-y:auto;border-left:1px solid #30363d;display:flex;flex-direction:column}
h2{color:#58a6ff;font-size:15px;margin-bottom:6px}
.tag{font-size:10px;color:#8b949e;margin-bottom:10px}
.o{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;margin:6px 0;font-size:12px}
.o .n{color:#3fb950;font-weight:bold}
.o .c{color:#7ee787;font-size:11px}
.bar{height:3px;background:#30363d;border-radius:2px;margin-top:3px}
.bar div{height:3px;background:#3fb950;border-radius:2px}
.btn{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:bold;margin:3px 0;width:100%}
.btn-go{background:#238636;color:#fff}.btn-go:hover{background:#2ea043}
.btn-estop{background:#da3633;color:#fff;font-size:18px;padding:16px;animation:pulse 1s infinite}
.btn-estop:hover{background:#f85149}
.btn-arm{background:#1f6feb;color:#fff}.btn-arm:hover{background:#388bfd}
.btn-reset{background:#6e7681;color:#fff;font-size:11px;padding:4px 10px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.7}}
#status{font-size:13px;margin:8px 0;padding:8px;border-radius:4px}
.status-ok{background:#0d3320;color:#3fb950}
.status-warn{background:#332000;color:#d2991d}
.status-err{background:#330000;color:#f85149}
</style></head>
<body>
<div class="l"><img src="/video_feed"></div>
<div class="r">
<h2>🍾 Bottle Grasp</h2>
<div class="tag" id="info">Loading...</div>
<div id="status" class="status-ok">Ready</div>
<div id="list"></div>
<div style="flex:1;min-height:10px"></div>
<button class="btn btn-arm" onclick="connect()">🔌 Connect Arm</button>
	<button class="btn btn-go" onclick="calibrateDesk()" style="background:#bc8c1f">📐 Calibrate Desk</button>
	<button class="btn btn-go" onclick="loadDesk()" style="background:#1f6feb">📂 Load Desk Ref</button>
<div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;margin:6px 0">
  <div style="font-size:11px;color:#8b949e;margin-bottom:4px">⚙ SCALE (实时可调)</div>
  <div style="display:flex;align-items:center;margin:3px 0">
    <span style="font-size:11px;width:18px;color:#58a6ff">X</span>
    <input type="range" id="scaleX" min="1" max="60" value="6" step="0.5"
           oninput="updateScale()" style="flex:1;accent-color:#58a6ff">
    <span id="scaleXVal" style="font-size:11px;width:52px;text-align:right;color:#58a6ff">0.000600</span>
  </div>
  <div style="display:flex;align-items:center;margin:3px 0">
    <span style="font-size:11px;width:18px;color:#3fb950">Y</span>
    <input type="range" id="scaleY" min="1" max="60" value="4" step="0.5"
           oninput="updateScale()" style="flex:1;accent-color:#3fb950">
    <span id="scaleYVal" style="font-size:11px;width:52px;text-align:right;color:#3fb950">0.000400</span>
  </div>
</div>
<button class="btn btn-estop" onclick="estop()" id="estop-btn">⏹ EMERGENCY STOP</button>
<button class="btn btn-reset" onclick="resetEstop()">↻ Reset E-STOP</button>
</div>
<script>
let poll=setInterval(async()=>{
  let r=await fetch('/objects');let d=await r.json();
  document.getElementById('info').textContent=d.count+' targets tracked | SCALE X='+(d.scale_x||0).toFixed(5)+' Y='+(d.scale_y||0).toFixed(5);
  let s=document.getElementById('status');
  s.textContent=d.status;
  s.className=d.estop?'status-err':(d.grasping?'status-warn':'status-ok');
  if(d.scale_x)document.getElementById('scaleXVal').textContent=d.scale_x.toFixed(6);
  if(d.scale_y)document.getElementById('scaleYVal').textContent=d.scale_y.toFixed(6);

  let h='';
  for(let o of d.objects){
    h+=`<div class="o">
      <span class="n">#${o.id} ${o.label}</span>${d.locked_id==o.id?' <span style="color:#c586c0;font-size:10px">🔒 LOCKED</span>':''} <span style="font-size:10px;color:#8b949e">${o.conf}</span>
      <div class="c">base (${o.bx}, ${o.by}, z≈${o.bz})m</div>
      <div class="bar"><div style="width:${(o.conf*100)|0}%"></div></div>
      <button class="btn btn-go" onclick="grasp(${o.id})" style="font-size:11px;margin-top:4px">🎯 Grasp #${o.id}</button>
	      <button class="btn btn-go" onclick="lockTrack(${o.id})" style="font-size:10px;margin-top:2px;background:#6e40c9">🔒 Lock #${o.id}</button>
    </div>`;
  }
  document.getElementById('list').innerHTML=h||'<div style="color:#8b949e;font-size:12px">No targets — place bottles on desk</div>';
},600);

async function grasp(id){await fetch('/grasp?id='+id)}
async function estop(){
  document.getElementById('estop-btn').style.background='#ff0000';
  await fetch('/estop');
}
async function resetEstop(){await fetch('/reset_estop')}
async function calibrateDesk(){
  document.getElementById('status').textContent='Detecting board...';
  let r=await fetch('/calibrate_desk');let d=await r.json();
  document.getElementById('status').textContent=d.status;
}
async function loadDesk(){
  let r=await fetch('/load_desk');let d=await r.json();
  document.getElementById('status').textContent=d.status;
}
async function lockTrack(id){await fetch('/lock_track?id='+id)}
async function connect(){let r=await fetch('/connect');let d=await r.json();document.getElementById('status').textContent=d.status}
let scaleTimer=null;
async function updateScale(){
  let sx=document.getElementById('scaleX').value/10000;
  let sy=document.getElementById('scaleY').value/10000;
  document.getElementById('scaleXVal').textContent=sx.toFixed(6);
  document.getElementById('scaleYVal').textContent=sy.toFixed(6);
  clearTimeout(scaleTimer);
  scaleTimer=setTimeout(async()=>{
    let r=await fetch('/set_scale?x='+sx+'&y='+sy);let d=await r.json();
    document.getElementById('status').textContent='SCALE: X='+d.scale_x.toFixed(6)+' Y='+d.scale_y.toFixed(6);
  },200);
}
</script>
</body></html>"""

# ============================================================
# Routes
# ============================================================
@app.route('/')
def index(): return render_template_string(HTML)

def gen():
    while True:
        with lock: f = display[0].copy() if display[0] is not None else None
        if f is not None:
            _, jpg = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+jpg.tobytes()+b'\r\n')
        time.sleep(0.04)

@app.route('/video_feed')
def video_feed():
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/objects')
def get_objects():
    with lock:
        tbs = dict(tracked_bottles)
        st = status_msg[0]
        es = estop_triggered[0]
        ga = grasp_active[0]
    objs = [{"id": tid, "label": o['label'], "conf": f"{o['conf']:.2f}",
             "cx": o['cx'], "cy": o['cy'],
             "bx": f"{o['bx']:.4f}", "by": f"{o['by']:.4f}", "bz": f"{o['bz']:.3f}"}
            for tid, o in sorted(tbs.items())]
    return jsonify({"count": len(objs), "objects": objs, "status": st,
                    "estop": es, "grasping": ga,
                    "desk_calibrated": desk_calibrated[0],
                    "locked_id": locked_track_id[0],
                    "scale_x": SCALE_X[0], "scale_y": SCALE_Y[0]})

@app.route('/lock_track')
def lock_track():
    tid = int(request.args.get('id', -1))
    locked_track_id[0] = tid if tid >= 0 else None
    if tid >= 0:
        return jsonify(status=f"Locked on #{tid}")
    else:
        return jsonify(status="Lock released")

@app.route('/set_scale')
def set_scale():
    """实时调整 SCALE 参数: /set_scale?x=0.0006&y=0.0004"""
    try:
        vx = float(request.args.get('x', SCALE_X[0]))
        vy = float(request.args.get('y', SCALE_Y[0]))
        SCALE_X[0] = max(0.0001, min(0.01, vx))
        SCALE_Y[0] = max(0.0001, min(0.01, vy))
        return jsonify(status=f"SCALE_X={SCALE_X[0]:.6f} SCALE_Y={SCALE_Y[0]:.6f}",
                       scale_x=SCALE_X[0], scale_y=SCALE_Y[0])
    except:
        return jsonify(status="Invalid scale value")

@app.route('/grasp')
def grasp():
    if estop_triggered[0]:
        return jsonify(status="E-STOP active! Reset first.")
    if grasp_active[0]:
        return jsonify(status="Grasp already in progress")
    tid = int(request.args.get('id', 0))
    # If locked, only allow grasping the locked bottle
    if locked_track_id[0] is not None and tid != locked_track_id[0]:
        return jsonify(status=f"Locked on #{locked_track_id[0]}, ignoring #{tid}")
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

@app.route('/reset_estop')
def reset_estop():
    global estop_triggered
    estop_triggered[0] = False
    status_msg[0] = "Ready"
    return jsonify(status="E-STOP reset")

@app.route('/connect')
def connect():
    if estop_triggered[0]:
        return jsonify(status="Reset E-STOP first")
    try:
        arm[0] = SingleArm(can_interface_="can0", enable_fd_=False)
        time.sleep(0.3)
        status_msg[0] = "Opening gripper + homing..."
        arm[0].setGripperPosition(GRIPPER_OPEN)
        time.sleep(0.3)
        arm[0].go_home()
        time.sleep(4.0)  # Wait for 3s motion + settle
        pos, euler = arm[0].get_ee_pose_euler()
        # Cache home camera pose for SEUCM offset computation
        T_base_ee = build_transform(pos, euler)
        T_base_camera_home[0] = T_base_ee @ T_flange_camera
        # Auto-load desk calibration if exists
        try:
            with open(DESK_REF_FILE) as f:
                data = json.load(f)
                T_base_board[0] = np.array(data['T_base_board'])
                desk_calibrated[0] = True
                Z_DESK = float(T_base_board[0][2, 3])
                status_msg[0] = f"Homed. Desk loaded Z={Z_DESK:.3f}m TCP:({pos[0]:.3f},{pos[1]:.3f},{pos[2]:.3f})"
        except:
            status_msg[0] = f"Homed. TCP:({pos[0]:.3f},{pos[1]:.3f},{pos[2]:.3f}) — place Charuco board, click Calibrate Desk"
        return jsonify(status=status_msg[0])
    except Exception as e:
        return jsonify(status=f"Connect failed: {e}")

@app.route('/calibrate_desk')
def calibrate_desk():
    global desk_calibrated, T_base_board
    if arm[0] is None:
        return jsonify(status="Connect arm first!")
    with lock:
        frame = rgb_frame[0].copy() if rgb_frame[0] is not None else None
    if frame is None:
        return jsonify(status="Camera not ready")

    def do_calibrate():
        global desk_calibrated, T_base_board, status_msg
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        rv, tv, _, mi = detect_board_pose(gray)
        n = len(mi) if mi is not None else 0
        if rv is None:
            status_msg[0] = f"Board NOT detected ({n} markers)"
            return
        try:
            T_camera_board = build_transform(tv.flatten(), rv.flatten())
            pos_ee, euler_ee = arm[0].get_ee_pose_euler()
            T_base_ee = build_transform(pos_ee, euler_ee)
            T_base_camera = T_base_ee @ T_flange_camera
            T_base_board[0] = T_base_camera @ T_camera_board
            desk_calibrated[0] = True
            with open(DESK_REF_FILE, 'w') as f:
                json.dump({'T_base_board': T_base_board[0].tolist()}, f, indent=2)
            t = T_base_board[0][:3, 3]
            print(f"Desk calibrated ({n} markers): origin=({t[0]:.4f},{t[1]:.4f},{t[2]:.4f})", flush=True)
            status_msg[0] = f"Desk calibrated! ({n} markers) Origin:({t[0]:.3f},{t[1]:.3f},{t[2]:.3f})m"
        except Exception as e:
            status_msg[0] = f"Calib error: {e}"

    status_msg[0] = "Detecting board..."
    th.Thread(target=do_calibrate, daemon=True).start()
    return jsonify(status="Detecting board... wait ~1s")

@app.route('/load_desk')
def load_desk():
    global desk_calibrated, T_base_board
    try:
        with open(DESK_REF_FILE) as f:
            data = json.load(f)
            T_base_board[0] = np.array(data['T_base_board'])
            desk_calibrated[0] = True
            t = T_base_board[0][:3, 3]
            return jsonify(status=f"Desk loaded. Board origin: ({t[0]:.3f},{t[1]:.3f},{t[2]:.3f})m")
    except Exception as e:
        return jsonify(status=f"Load failed: {e}. Calibrate desk first.")

@app.route('/diag')
def diag():
    """诊断端点: 对比像素偏移 vs SEUCM几何法 的移动方向符号。

    用法: 浏览器打开 http://192.168.58.68:8088/diag
    前提: 已 Connect Arm + Calibrate Desk(或 Load Desk Ref) + 桌面有瓶子被检测到

    输出解读:
      - x_match=true, y_match=true  → 像素映射符号正确
      - x_match=false → X轴(dx)符号反了，需要 dx = -dv * SCALE_X
      - y_match=false → Y轴(dy)符号反了，需要 dy = +du * SCALE_Y
    """
    with lock:
        tbs = dict(tracked_bottles)

    if arm[0] is None:
        return jsonify(status="❌ Arm not connected. Click 'Connect Arm' first.")

    if not tbs:
        return jsonify(status="❌ No bottles detected. Place a bottle on the desk and wait for YOLO.")

    pos, euler = arm[0].get_ee_pose_euler()

    # 取第一个追踪到的瓶子
    tid, obj = next(iter(tbs.items()))
    cx, cy = obj['cx'], obj['cy']

    # ---- 方法1: 像素偏移 (当前方案) ----
    du = cx - U0
    dv = cy - V0
    sx, sy = SCALE_X[0], SCALE_Y[0]
    dx_pix = dv * sx
    dy_pix = -du * sy

    # ---- 方法2: SEUCM 几何求交 (ground truth) ----
    p_base = bottle_position_in_base(cx, cy)

    result = {
        "bottle": f"#{tid} {obj.get('label','?')} conf={obj.get('conf',0):.2f}",
        "pixel": {"cx": cx, "cy": cy, "du": round(du, 1), "dv": round(dv, 1)},
        "pixel_offset": {
            "dx": round(dx_pix, 4), "dy": round(dy_pix, 4),
            "dx_sign": "+X(前)" if dx_pix > 0 else "-X(后)",
            "dy_sign": "+Y(左)" if dy_pix > 0 else "-Y(右)",
        },
        "ee_pos": {"x": round(float(pos[0]), 4), "y": round(float(pos[1]), 4), "z": round(float(pos[2]), 4)},
    }

    if p_base is not None:
        dx_geo = float(p_base[0] - pos[0])
        dy_geo = float(p_base[1] - pos[1])
        dz_geo = float(p_base[2] - pos[2])

        x_match = dx_pix * dx_geo > 0 if abs(dx_geo) > 0.001 else None
        y_match = dy_pix * dy_geo > 0 if abs(dy_geo) > 0.001 else None

        result["geometric"] = {
            "bottle_xyz": [round(float(p_base[0]), 4), round(float(p_base[1]), 4), round(float(p_base[2]), 4)],
            "offset": {"dx": round(dx_geo, 4), "dy": round(dy_geo, 4), "dz": round(dz_geo, 4)},
            "dx_sign": "+X(前)" if dx_geo > 0 else "-X(后)",
            "dy_sign": "+Y(左)" if dy_geo > 0 else "-Y(右)",
        }
        result["sign_check"] = {
            "x_match": "✅ SAME" if x_match else ("❌ FLIP" if x_match is False else "⚪ too small"),
            "y_match": "✅ SAME" if y_match else ("❌ FLIP" if y_match is False else "⚪ too small"),
        }

        fixes = []
        if x_match is False:
            fixes.append("X轴: dx = -dv * SCALE_X  (翻转 dv 的符号)")
        if y_match is False:
            fixes.append("Y轴: dy = +du * SCALE_Y  (翻转 du 的符号)")

        if not fixes:
            result["verdict"] = "✅ 符号一致 — 像素映射方向正确"
        else:
            result["verdict"] = f"❌ 符号不一致! 需要修改: {'; '.join(fixes)}"
    else:
        # SEUCM几何方法失败 → 用 Homography 作为备选参考
        result["geometric"] = None
        geo_reasons = []

        if not desk_calibrated[0] or T_base_board[0] is None:
            geo_reasons.append("桌面未标定")
        else:
            ray_cam = unproject(cx, cy)
            if ray_cam is None:
                geo_reasons.append("SEUCM unproject 失败")
            else:
                T_base_cam = build_transform(pos, euler) @ T_flange_camera
                R_base_cam = T_base_cam[:3, :3]
                cam_pos = T_base_cam[:3, 3]
                ray_base = R_base_cam @ ray_cam
                T_board_base = inv_transform(T_base_board[0])
                cam_in_board = T_board_base[:3, :3] @ cam_pos + T_board_base[:3, 3]
                ray_in_board = T_board_base[:3, :3] @ ray_base
                if abs(ray_in_board[2]) < 1e-10:
                    geo_reasons.append("射线平行桌面")
                else:
                    lam = -cam_in_board[2] / ray_in_board[2]
                    if lam < 0:
                        geo_reasons.append(f"射线不交桌面(像素太靠边)")
                    else:
                        geo_reasons.append(f"未知(lam={lam:.3f})")

        # ---- 备选: Homography 方法 (2D平面映射, 无鱼眼限制) ----
        try:
            pt_h = pixel_to_base(cx, cy)
            dx_h = float(pt_h[0] - pos[0])
            dy_h = float(pt_h[1] - pos[1])

            x_match_h = dx_pix * dx_h > 0 if abs(dx_h) > 0.001 else None
            y_match_h = dy_pix * dy_h > 0 if abs(dy_h) > 0.001 else None

            result["homography_ref"] = {
                "bottle_xy": [round(float(pt_h[0]), 4), round(float(pt_h[1]), 4)],
                "offset": {"dx": round(dx_h, 4), "dy": round(dy_h, 4)},
                "dx_sign": "+X(前)" if dx_h > 0 else "-X(后)",
                "dy_sign": "+Y(左)" if dy_h > 0 else "-Y(右)",
            }
            result["sign_check"] = {
                "x_match": "✅ SAME" if x_match_h else ("❌ FLIP" if x_match_h is False else "⚪ too small"),
                "y_match": "✅ SAME" if y_match_h else ("❌ FLIP" if y_match_h is False else "⚪ too small"),
                "ref": "homography",
            }

            fixes = []
            if x_match_h is False:
                fixes.append("X轴: dx = -dv * SCALE_X")
            if y_match_h is False:
                fixes.append("Y轴: dy = +du * SCALE_Y")

            if not fixes:
                result["verdict"] = "✅ 符号一致 (Homography参考) — 像素映射方向正确"
            else:
                result["verdict"] = f"❌ 符号不一致! 需要修改: {'; '.join(fixes)}"

            # Console log
            print(f"   几何方法失败 ({'; '.join(geo_reasons)}), 改用Homography", flush=True)
            print(f"   Homography: dx={dx_h:+.4f} ({'前' if dx_h>0 else '后'})  "
                  f"dy={dy_h:+.4f} ({'左' if dy_h>0 else '右'})", flush=True)

        except Exception as e_h:
            result["verdict"] = f"⚠️ Homography 也失败: {e_h}"

    # Console log
    print(f"\n{'='*60}", flush=True)
    print(f"🔍 DIAG #{tid}: pixel({cx},{cy}) du={du:.0f} dv={dv:.0f}", flush=True)
    print(f"   像素偏移:  dx={dx_pix:+.4f} ({'前' if dx_pix>0 else '后'})  "
          f"dy={dy_pix:+.4f} ({'左' if dy_pix>0 else '右'})", flush=True)
    if p_base is not None:
        print(f"   几何求交:  dx={dx_geo:+.4f} ({'前' if dx_geo>0 else '后'})  "
              f"dy={dy_geo:+.4f} ({'左' if dy_geo>0 else '右'})", flush=True)
    print(f"   结论: {result['verdict']}", flush=True)
    print(f"{'='*60}\n", flush=True)

    return jsonify(result)


if __name__ == '__main__':
    th.Thread(target=capture_loop, daemon=True).start()
    time.sleep(4)
    print("Bottle Grasp: http://192.168.58.68:8088")
    app.run(host='0.0.0.0', port=8088, debug=False, threaded=True)
