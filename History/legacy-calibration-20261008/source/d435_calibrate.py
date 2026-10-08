"""
D435 hand-eye calibration — ChArUco board + robot flange poses.
  http://<IP>:8092

Same ChArUco board as Lumos calibration (handeye_calib.py:8089).
Key difference: D435 uses standard pinhole model (no SEUCM).
"""
import cv2, numpy as np, json, time, sys, os, threading as th
import pyrealsense2 as rs
from flask import Flask, Response, render_template_string, jsonify, request

sys.path.insert(0, '/home/nieqingcao/arm/startouch_sdk/interface_py')
from startouchclass import SingleArm

# ============================================================
# ChArUco board (same as handeye_calib.py)
SX, SY = 9, 12
SL, ML = 0.015, 0.01125
aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
board = cv2.aruco.CharucoBoard((SX, SY), SL, ML, aruco_dict)
board_obj, board_ids = board.getObjPoints(), board.getIds()
board_id_set = set(board_ids.flatten())
detector_params = cv2.aruco.DetectorParameters()

app = Flask(__name__)

# State
display = [None]
rgb_frame = [None]
K = [None]              # 3x3 intrinsics from D435
DIST = np.zeros(5)      # Pinhole dist coeffs
arm = [None]
arm_connected = [False]
poses = []              # [(R_flange_base, t_flange_base, R_board_cam, t_board_cam), ...]
lock = th.Lock()
status = ["Ready — move arm to see board, click Capture"]
d435_pipeline = [None]
d435_align = [None]


def start_d435():
    """Start D435 pipeline for RGB frames."""
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    try:
        profile = pipeline.start(config)
        # Read intrinsics from D435
        intrinsics = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
        K[0] = np.array([[intrinsics.fx, 0, intrinsics.ppx],
                         [0, intrinsics.fy, intrinsics.ppy],
                         [0, 0, 1]], dtype=np.float64)
        DIST[:] = np.array(intrinsics.coeffs, dtype=np.float64)
        print(f"D435 intrinsics: fx={intrinsics.fx:.1f}, fy={intrinsics.fy:.1f}, "
              f"ppx={intrinsics.ppx:.1f}, ppy={intrinsics.ppy:.1f}")
        # Warm up
        for _ in range(15):
            pipeline.wait_for_frames()
        print("D435 calibration stream ready.")
        return pipeline
    except Exception as e:
        print(f"D435 start error: {e}")
        return None


def capture_loop():
    """Continuous frame capture from D435."""
    global display, rgb_frame
    pipeline = start_d435()
    if pipeline is None:
        print("D435 not available")
        return
    d435_pipeline[0] = pipeline

    while pipeline is not None:
        try:
            frames = pipeline.wait_for_frames(timeout_ms=2000)
            color_frame = frames.get_color_frame()
            if not color_frame:
                time.sleep(0.01); continue
            frame = np.asanyarray(color_frame.get_data())
        except Exception as e:
            time.sleep(0.1); continue

        with lock:
            rgb_frame[0] = frame.copy()

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Detect board
        rvec, tvec, mc, mi = detect_board(gray)
        if mc is not None and mi is not None and rvec is not None:
            cv2.aruco.drawDetectedMarkers(frame, mc, mi)
            cv2.drawFrameAxes(frame, K[0], DIST, rvec, tvec, 0.03)
            t = tvec.flatten()
            cv2.putText(frame, f"Board: ({t[0]:.3f},{t[1]:.3f},{t[2]:.3f})m",
                        (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
            cv2.putText(frame, f"Markers: {len(mi)} | Pairs: {len(poses)}",
                        (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
        else:
            n = len(mi) if mi is not None else 0
            cv2.putText(frame, f"No board ({n} markers) | Pairs: {len(poses)}",
                        (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 255), 1)

        with lock:
            display[0] = frame.copy()
        time.sleep(0.03)


def detect_board(gray):
    """Detect ChArUco board, return (rvec, tvec, mc, mi) using K[0]."""
    if K[0] is None:
        return None, None, None, None
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
        return None, None, mc, mi

    obj_pts = np.array(obj_pts, dtype=np.float64).reshape(-1, 3)
    img_pts = np.array(img_pts, dtype=np.float64).reshape(-1, 2)

    ok, rvec, tvec = cv2.solvePnP(obj_pts, img_pts, K[0], DIST,
                                   flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        return None, None, mc, mi
    return rvec, tvec, mc, mi


def build_transform(pos, euler):
    R, _ = cv2.Rodrigues(np.array(euler, dtype=np.float64))
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = pos
    return T


HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>D435 Hand-Eye Calib</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,sans-serif;display:flex;height:100vh}
.l{flex:1;display:flex;align-items:center;justify-content:center;padding:8px}
.l img{max-width:100%;max-height:98vh;border:2px solid #30363d;border-radius:8px}
.r{width:300px;padding:14px;background:#161b22;overflow-y:auto;border-left:1px solid #30363d}
h2{color:#58a6ff;font-size:15px;margin-bottom:6px}
.btn{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:bold;margin:4px 0;width:100%}
.btn-go{background:#238636;color:#fff}.btn-go:hover{background:#2ea043}
.btn-cal{background:#1f6feb;color:#fff}.btn-cal:hover{background:#388bfd}
.btn-danger{background:#da3633;color:#fff}
.info{font-size:12px;color:#8b949e;margin:4px 0}
.status{font-size:12px;margin:8px 0;padding:8px;border-radius:4px;background:#0d3320;color:#3fb950}
pre{background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:8px;font-size:11px;color:#7ee787;overflow-x:auto;max-height:200px}
</style></head><body>
<div class="l"><img src="/video_feed"></div>
<div class="r">
<h2>🤖 D435 Hand-Eye Calib</h2>
<div class="info">ChArUco 9×12 · 15mm · DICT_5X5_100</div>
<div class="info">Fix board on desk — DO NOT MOVE IT</div>
<div class="status" id="status">Loading...</div>

<button class="btn btn-go" onclick="connect()">🔌 Connect Arm</button>
<button class="btn btn-go" onclick="capture()">📸 Capture Pose</button>
<button class="btn btn-cal" onclick="calibrate()">📐 Compute T_flange_d435cam</button>
<button class="btn btn-danger" onclick="resetp()">🗑 Clear All</button>

<div class="info" id="count">Pairs: 0 (need ≥6)</div>
<pre id="result">Waiting for calibration...</pre>
</div>
<script>
async function poll(){let r=await fetch('/status');let d=await r.json();
  document.getElementById('status').textContent=d.status;
  document.getElementById('count').textContent='Pairs: '+d.pairs+' (need ≥6)';
}setInterval(poll,1000);poll();

async function connect(){let r=await fetch('/connect');let d=await r.json();
  document.getElementById('status').textContent=d.status;}
async function capture(){let r=await fetch('/capture');let d=await r.json();
  document.getElementById('status').textContent=d.status;}
async function calibrate(){let r=await fetch('/calibrate');let d=await r.json();
  document.getElementById('result').textContent=d.result;
  document.getElementById('status').textContent=d.status;}
async function resetp(){await fetch('/reset');location.reload();}
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
    return jsonify({"pairs": len(poses), "connected": arm_connected[0], "status": status[0]})

@app.route('/connect')
def connect():
    try:
        arm[0] = SingleArm(can_interface_="can0", enable_fd_=False)
        time.sleep(0.3)
        arm[0].get_ee_pose_euler()
        arm_connected[0] = True
        status[0] = "Arm connected. Move arm to see board, click Capture."
        return jsonify(status=status[0])
    except Exception as e:
        return jsonify(status=f"Connect failed: {e}")

@app.route('/capture')
def capture_one():
    if not arm_connected[0]:
        return jsonify(status="Connect arm first!")

    with lock:
        frame = rgb_frame[0].copy() if rgb_frame[0] is not None else None

    if frame is None:
        return jsonify(status="Camera not ready — wait for stream")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    rvec, tvec, _, _ = detect_board(gray)

    if rvec is None:
        return jsonify(status="Board not detected! Adjust arm position.")

    # Get flange pose
    pos, euler = arm[0].get_ee_pose_euler()
    R_flange_base = cv2.Rodrigues(np.array(euler, dtype=np.float64))[0]
    t_flange_base = np.array(pos, dtype=np.float64).reshape(3, 1)

    # Board pose in camera frame: invert solvePnP result (camera→board)
    R_board_cam = cv2.Rodrigues(rvec)[0]
    t_board_cam = tvec.reshape(3, 1)

    poses.append((R_flange_base, t_flange_base, R_board_cam, t_board_cam))
    status[0] = f"Captured! {len(poses)} pairs. t_board_cam=({t_board_cam[0,0]:.3f},{t_board_cam[1,0]:.3f},{t_board_cam[2,0]:.3f})"
    return jsonify(status=status[0])


def handeye_tsai(R_a_list, t_a_list, R_b_list, t_b_list):
    """Tsai hand-eye calibration: solve AX = XB.
    A: flange→base motion, B: board→cam motion. Returns X: cam→flange (4×4)."""
    n = len(R_a_list)
    n_pairs = n * (n - 1) // 2
    P = np.zeros((3 * n_pairs, 3))
    q = np.zeros((3 * n_pairs,))
    idx = 0
    for i in range(n):
        for j in range(i + 1, n):
            p_a = cv2.Rodrigues(R_a_list[j].T @ R_a_list[i])[0].flatten()
            p_b = cv2.Rodrigues(R_b_list[j].T @ R_b_list[i])[0].flatten()
            skew = np.array([[0, -p_a[2] - p_b[2], p_a[1] + p_b[1]],
                             [p_a[2] + p_b[2], 0, -p_a[0] - p_b[0]],
                             [-p_a[1] - p_b[1], p_a[0] + p_b[0], 0]])
            P[idx:idx + 3] = skew
            q[idx:idx + 3] = p_b - p_a
            idx += 3
    p_c = np.linalg.lstsq(P, q, rcond=None)[0]
    R_x = cv2.Rodrigues(p_c)[0]

    A = np.zeros((3 * n_pairs, 3))
    b = np.zeros((3 * n_pairs,))
    idx = 0
    for i in range(n):
        for j in range(i + 1, n):
            A[idx:idx + 3] = R_a_list[j] - np.eye(3)
            b[idx:idx + 3] = R_x @ t_b_list[j].flatten() - t_a_list[j].flatten()
            idx += 3
    t_x = np.linalg.lstsq(A, b, rcond=None)[0]

    T = np.eye(4)
    T[:3, :3] = R_x
    T[:3, 3] = t_x
    return T


@app.route('/calibrate')
def calibrate():
    if len(poses) < 5:
        return jsonify(result="", status=f"Need ≥5 pairs, have {len(poses)}")

    R_flange = [p[0].copy() for p in poses]
    t_flange = [p[1].copy() for p in poses]
    R_board = [p[2].copy() for p in poses]
    t_board = [p[3].copy() for p in poses]

    try:
        # handeye_tsai returns T_cam_flange (camera in flange frame)
        T_cam_flange = handeye_tsai(R_flange, t_flange, R_board, t_board)

        # Invert to get T_flange_camera
        R_cam_flange = T_cam_flange[:3, :3]
        t_cam_flange = T_cam_flange[:3, 3].reshape(3, 1)
        R_flange_cam = R_cam_flange.T
        t_flange_cam = -R_cam_flange.T @ t_cam_flange
        T_flange_camera = np.eye(4)
        T_flange_camera[:3, :3] = R_flange_cam
        T_flange_camera[:3, 3] = t_flange_cam.flatten()

        lines = [
            f"D435 Hand-Eye Calibrated ({len(poses)} pairs, Tsai method)",
            "",
            "T_flange_d435cam (camera in flange frame) =",
        ]
        for row in T_flange_camera:
            lines.append(f"  [{row[0]:.6f}, {row[1]:.6f}, {row[2]:.6f}, {row[3]:.6f}]")

        result = {"T_flange_d435cam": T_flange_camera.tolist(), "pairs": len(poses),
                  "method": "OpenCV calibrateHandEye TSAI"}
        with open('/home/nieqingcao/calibration/d435_handeye_result.json', 'w') as f:
            json.dump(result, f, indent=2)

        lines.append("")
        lines.append("Saved to d435_handeye_result.json")
        status[0] = f"Calibrated! {len(poses)} pairs."

        return jsonify(result="\n".join(lines), status=status[0])

    except Exception as e:
        import traceback
        return jsonify(result=f"Error: {e}\n{traceback.format_exc()}", status="Calibration failed")


@app.route('/reset')
def reset():
    global poses
    poses = []
    status[0] = "Cleared"
    return jsonify(status="Cleared")


if __name__ == '__main__':
    th.Thread(target=capture_loop, daemon=True).start()
    time.sleep(2)
    print("D435 Hand-Eye Calibration: http://192.168.58.68:8092")
    app.run(host='0.0.0.0', port=8092, debug=False, threaded=True)
