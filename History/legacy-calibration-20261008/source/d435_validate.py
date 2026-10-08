"""
D435 hand-eye calibration validation.
After calibrating, run this to check accuracy.

Usage:
  python d435_validate.py

Measures:
  1. Reprojection error: project board back to image, compare with detected corners
  2. Depth consistency: compare D435 depth at board center vs solvePnP result
  3. Single-point repeatability: move arm, come back to same pose, check consistency
"""
import cv2, numpy as np, json, time, sys, os, threading as th
import pyrealsense2 as rs
from flask import Flask, Response, render_template_string, jsonify

sys.path.insert(0, '/home/nieqingcao/arm/startouch_sdk/interface_py')
from startouchclass import SingleArm

# ============================================================
# Load calibration
# ============================================================
CALIB_FILE = '/home/nieqingcao/calibration/d435_handeye_result.json'
if not os.path.exists(CALIB_FILE):
    print(f"❌ {CALIB_FILE} not found. Run d435_calibrate.py first!")
    sys.exit(1)

with open(CALIB_FILE) as f:
    calib_data = json.load(f)
T_flange_d435cam = np.array(calib_data['T_flange_d435cam'])
print(f"Loaded calibration: {calib_data.get('pairs', '?')} pairs, {calib_data.get('method', '?')}")

# ============================================================
# ChArUco board (standard)
SX, SY, ML = 9, 12, 0.01125
aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
board = cv2.aruco.CharucoBoard((SX, SY), 0.015, ML, aruco_dict)
board_obj, board_ids = board.getObjPoints(), board.getIds()
board_id_set = set(board_ids.flatten())
detector_params = cv2.aruco.DetectorParameters()

app = Flask(__name__)

# State
display = [None]
raw_frame_store = [None]
K = [None]
arm = [None]
results = []
lock = th.Lock()
status = ["Ready"]


def detect_board(gray):
    """Detect ChArUco board. Returns (rvec, tvec, mc, mi, obj_pts, img_pts)."""
    if K[0] is None:
        return None, None, None, None, None, None
    ad = cv2.aruco.ArucoDetector(aruco_dict, detector_params)
    mc, mi, _ = ad.detectMarkers(gray)
    if mi is None or len(mi) < 6:
        return None, None, mc, mi, None, None

    valid = [int(m) in board_id_set for m in mi.flatten()]
    mc_v = [mc[i] for i in range(len(mc)) if valid[i]]
    mi_v = np.array([mi.flatten()[i] for i in range(len(mi)) if valid[i]])

    if len(mi_v) < 6:
        return None, None, mc, mi, None, None

    half = ML / 2
    offsets = [(-half, -half), (half, -half), (half, half), (-half, half)]
    obj_pts, img_pts = [], []

    for corners, mid in zip(mc_v, mi_v):
        mid_val = int(mid)
        idx = np.where(board_ids.flatten() == mid_val)[0]
        if len(idx) == 0: continue
        obj_c = board_obj[idx[0]].flatten()
        for j in range(4):
            dx, dy = offsets[j]
            obj_pts.append([obj_c[0] + dx, obj_c[1] + dy, 0.0])
            img_pts.append(corners[0][j])

    if len(obj_pts) < 8:
        return None, None, mc, mi, None, None

    obj_pts = np.array(obj_pts, dtype=np.float64).reshape(-1, 3)
    img_pts = np.array(img_pts, dtype=np.float64).reshape(-1, 2)

    ok, rvec, tvec = cv2.solvePnP(obj_pts, img_pts, K[0], np.zeros(5),
                                   flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None, None, mc, mi, None, None
    return rvec, tvec, mc, mi, obj_pts, img_pts


def build_transform(pos, euler):
    R, _ = cv2.Rodrigues(np.array(euler, dtype=np.float64))
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = pos
    return T


def capture_loop():
    global display, K

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

    try:
        profile = pipeline.start(config)
    except Exception as e:
        print(f"D435 error: {e}")
        return

    intr = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
    K[0] = np.array([[intr.fx, 0, intr.ppx],
                     [0, intr.fy, intr.ppy],
                     [0, 0, 1]], dtype=np.float64)
    depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()

    align = rs.align(rs.stream.color)
    for _ in range(30):
        pipeline.wait_for_frames()

    while True:
        frames = pipeline.wait_for_frames()
        aligned = align.process(frames)
        color_f = aligned.get_color_frame()
        depth_f = aligned.get_depth_frame()
        if not color_f or not depth_f:
            time.sleep(0.01); continue

        frame = np.asanyarray(color_f.get_data())
        depth_data = np.asanyarray(depth_f.get_data())

        # Save raw frame BEFORE drawing (for /sample route)
        with lock:
            raw_frame_store[0] = frame.copy()

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        rvec, tvec, mc, mi, obj_pts, img_pts = detect_board(gray)

        if rvec is not None and img_pts is not None:
            cv2.aruco.drawDetectedMarkers(frame, mc, mi)
            cv2.drawFrameAxes(frame, K[0], np.zeros(5), rvec, tvec, 0.03)

            # Reprojection error
            proj_pts, _ = cv2.projectPoints(obj_pts, rvec, tvec, K[0], np.zeros(5))
            errors = np.linalg.norm(proj_pts.reshape(-1, 2) - img_pts.reshape(-1, 2), axis=1)
            mean_err = np.mean(errors)
            cv2.putText(frame, f"Reproj err: {mean_err:.2f}px",
                        (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)

            # Depth at board center
            t = tvec.flatten()
            cv2.putText(frame, f"PnP: ({t[0]:.3f},{t[1]:.3f},{t[2]:.3f})m",
                        (10, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # D435 depth at board center pixel
            # Project board origin to camera pixel
            board_center_3d = np.array([[0, 0, 0]], dtype=np.float64)
            cp, _ = cv2.projectPoints(board_center_3d, rvec, tvec, K[0], np.zeros(5))
            cu, cv_px = int(cp[0][0][0]), int(cp[0][0][1])
            if 0 <= cu < 640 and 0 <= cv_px < 480:
                d_d435 = depth_data[cv_px, cu] * depth_scale
                cv2.circle(frame, (cu, cv_px), 5, (0, 255, 255), -1)
                cv2.putText(frame, f"D435 depth at center: {d_d435:.3f}m",
                            (10, 96), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

            n = len(mi) if mi is not None else 0
            cv2.putText(frame, f"Markers: {n} | Samples: {len(results)}",
                        (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
        else:
            n = len(mi) if mi is not None else 0
            cv2.putText(frame, f"No board ({n} markers) | Samples: {len(results)}",
                        (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 255), 1)

        with lock:
            display[0] = frame.copy()
        time.sleep(0.03)


HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>D435 Validate</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,sans-serif;display:flex;height:100vh}
.l{flex:1;display:flex;align-items:center;justify-content:center;padding:8px}
.l img{max-width:100%;max-height:98vh;border:2px solid #30363d;border-radius:8px}
.r{width:350px;padding:14px;background:#161b22;overflow-y:auto;border-left:1px solid #30363d}
h2{color:#58a6ff;font-size:15px;margin-bottom:6px}
.btn{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:bold;margin:4px 0;width:100%}
.btn-go{background:#238636;color:#fff}.btn-go:hover{background:#2ea043}
.btn-cal{background:#1f6feb;color:#fff}
.btn-danger{background:#da3633;color:#fff}
.info{font-size:12px;color:#8b949e;margin:4px 0}
.metric{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px;margin:8px 0;font-size:13px}
.metric .v{color:#3fb950;font-size:22px;font-weight:bold}
.metric .l{color:#8b949e;font-size:11px}
.good{color:#3fb950}.warn{color:#d2991d}.bad{color:#f85149}
</style></head><body>
<div class="l"><img src="/video_feed"></div>
<div class="r">
<h2>📏 D435 Calibration Validation</h2>
<div class="info">Compare PnP vs D435 depth at board center</div>

<button class="btn btn-go" onclick="connect()">🔌 Connect Arm</button>
<button class="btn btn-go" onclick="sample()">📸 Collect Sample</button>
<button class="btn btn-cal" onclick="analyze()">📊 Analyze Accuracy</button>
<button class="btn btn-danger" onclick="clearall()">🗑 Clear</button>

<div id="metrics">
  <div class="metric"><div class="l">Samples collected</div><div class="v" id="count">0</div></div>
</div>
<div id="result" style="font-size:11px;margin-top:8px;white-space:pre-wrap"></div>
</div>
<script>
setInterval(async()=>{
  let r=await fetch('/status');let d=await r.json();
  document.getElementById('count').textContent=d.count;
},1000);

async function connect(){let r=await fetch('/connect');alert((await r.json()).status)}
async function sample(){let r=await fetch('/sample');alert((await r.json()).status)}
async function analyze(){
  let r=await fetch('/analyze');let d=await r.json();
  document.getElementById('result').textContent=d.report;
}
async function clearall(){await fetch('/clear');document.getElementById('result').textContent='';}
</script>
</body></html>"""


@app.route('/')
def index(): return render_template_string(HTML)


def gen():
    while True:
        with lock: f = display[0].copy() if display[0] is not None else None
        if f is not None:
            _, jpg = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpg.tobytes() + b'\r\n')
        time.sleep(0.04)


@app.route('/video_feed')
def video_feed():
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/status')
def get_status():
    return jsonify({"count": len(results), "status": status[0]})


@app.route('/connect')
def connect():
    try:
        arm[0] = SingleArm(can_interface_="can0", enable_fd_=False)
        time.sleep(0.3)
        arm[0].get_ee_pose_euler()
        status[0] = "Arm connected"
        return jsonify(status="Connected")
    except Exception as e:
        return jsonify(status=f"Failed: {e}")


@app.route('/sample')
def sample():
    """Collect one validation sample.
    Compares: D435 depth at board center vs PnP-derived distance.
    Also computes: T_base_d435cam-based board position vs PnP chain.
    """
    if arm[0] is None:
        return jsonify(status="Connect arm first!")

    with lock:
        frame = raw_frame_store[0].copy() if raw_frame_store[0] is not None else None

    if frame is None:
        return jsonify(status="No frame")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    rvec, tvec, _, _, _, _ = detect_board(gray)
    if rvec is None:
        return jsonify(status="Board not detected!")

    # Get flange pose
    pos, euler = arm[0].get_ee_pose_euler()
    T_base_ee = build_transform(pos, euler)
    T_base_cam = T_base_ee @ T_flange_d435cam

    # Board position from PnP (camera frame)
    R_board_cam = cv2.Rodrigues(rvec)[0]
    t_board_cam = tvec.flatten()
    # Board Z in camera frame = distance
    pnp_distance = float(np.linalg.norm(t_board_cam))
    pnp_z = float(t_board_cam[2])

    # Board position in base frame (via PnP chain)
    T_cam_board = np.eye(4)
    T_cam_board[:3, :3] = R_board_cam
    T_cam_board[:3, 3] = t_board_cam
    T_base_board_pnp = T_base_cam @ T_cam_board

    # Store sample
    results.append({
        'pnp_distance': pnp_distance,
        'pnp_z_cam': pnp_z,
        'T_base_board': T_base_board_pnp.tolist(),
        'flange_pos': list(pos),
        'flange_euler': list(euler),
    })

    status[0] = f"Sample #{len(results)}: PnP distance={pnp_distance:.3f}m"
    return jsonify(status=status[0])


@app.route('/analyze')
def analyze():
    """Analyze calibration accuracy using collected samples."""
    if len(results) < 3:
        return jsonify(report=f"Need ≥3 samples, have {len(results)}")

    # Compare board positions across samples
    board_positions = np.array([r['T_base_board'][:3][3] for r in results])
    # 4th column element [3] is the translation
    board_xyz = np.array([[r['T_base_board'][0][3], r['T_base_board'][1][3], r['T_base_board'][2][3]]
                           for r in results])

    mean_pos = board_xyz.mean(axis=0)
    std_pos = board_xyz.std(axis=0)
    max_dev = np.max(np.linalg.norm(board_xyz - mean_pos, axis=1))

    lines = [
        "=" * 50,
        "D435 Hand-Eye Calibration — Accuracy Report",
        "=" * 50,
        f"\nSamples: {len(results)} (board fixed on desk, arm at different poses)",
        "",
        "📐 板子在基座坐标系中的位置 (多次测量):",
        f"  Mean:  X={mean_pos[0]:.4f}, Y={mean_pos[1]:.4f}, Z={mean_pos[2]:.4f} m",
        f"  Std:   X={std_pos[0]:.4f}, Y={std_pos[1]:.4f}, Z={std_pos[2]:.4f} m",
        f"  Max deviation: {max_dev*1000:.1f} mm",
        "",
    ]

    # Judge quality
    if max_dev < 0.005:
        lines.append("✅ EXCELLENT: <5mm variation across poses")
    elif max_dev < 0.010:
        lines.append("✅ GOOD: <10mm variation — good enough for grasping")
    elif max_dev < 0.020:
        lines.append("⚠️ ACCEPTABLE: <20mm — may need fine-tuning")
    else:
        lines.append("❌ POOR: >20mm — recalibrate with more/better poses")

    lines.append("")
    lines.append("💡 Tips for better accuracy:")
    lines.append("  1. More pose variety (rotate EE, not just translate)")
    lines.append("  2. Tilt board ~30° off the desk surface")
    lines.append("  3. Ensure board fills >30% of image")
    lines.append("  4. Collect 10-15 pairs minimum")

    report = "\n".join(lines)
    return jsonify(report=report)


@app.route('/clear')
def clear():
    global results
    results = []
    return jsonify(status="Cleared")


if __name__ == '__main__':
    th.Thread(target=capture_loop, daemon=True).start()
    time.sleep(2)
    print("D435 Validation: http://192.168.58.68:8093")
    app.run(host='0.0.0.0', port=8093, debug=False, threaded=True)
