"""
ChArUco Calibration — web-based, works over SSH
  http://<IP>:8081
"""
import cv2
import numpy as np
import json
import os
import time
import threading
import traceback
from flask import Flask, Response, render_template_string, request, jsonify

app = Flask(__name__)

# ============================================================
SQUARES_X = 9
SQUARES_Y = 12
SQUARE_LENGTH = 0.015     # 15mm
MARKER_LENGTH = 0.01125   # 11.25mm
# ============================================================

rgb_frame = None
display_frame = None
lock = threading.Lock()
calib_images = []
calib_result = None
desktop_result = None
SAVE_DIR = "/home/nieqingcao/calibration/captured_images"

# Restore saved images from disk
os.makedirs(SAVE_DIR, exist_ok=True)
for fname in sorted(os.listdir(SAVE_DIR)):
    if fname.endswith('.npz'):
        data = np.load(os.path.join(SAVE_DIR, fname))
        calib_images.append((data['corners'], data['ids']))
if calib_images:
    print(f"Loaded {len(calib_images)} saved images from disk")

# ChArUco board
aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
board = cv2.aruco.CharucoBoard((SQUARES_X, SQUARES_Y), SQUARE_LENGTH, MARKER_LENGTH, aruco_dict)
detector_params = cv2.aruco.DetectorParameters()

if hasattr(cv2.aruco, 'ArucoDetector'):
    aruco_detector = cv2.aruco.ArucoDetector(aruco_dict, detector_params)
    use_new_api = True
else:
    aruco_detector = None
    use_new_api = False

board_obj_points, board_ids_ref = board.getObjPoints(), board.getIds()


def detect_board_opencv5(gray):
    """Detect markers and extract corner points for calibration."""
    mc, mi, _ = aruco_detector.detectMarkers(gray)
    if mi is None or len(mi) < 4:
        return None, None, mc, mi

    board_ids = set(board_ids_ref.flatten())
    valid_mask = [int(mid) in board_ids for mid in mi.flatten()]
    mc_valid = [mc[i] for i in range(len(mc)) if valid_mask[i]]
    mi_valid = np.array([mi.flatten()[i] for i in range(len(mi)) if valid_mask[i]])

    if len(mi_valid) < 4:
        return None, None, mc, mi

    half = MARKER_LENGTH / 2
    marker_corners_local = np.array([
        [-half, -half], [half, -half], [half, half], [-half, half],
    ])

    all_img_pts = []
    all_cids = []

    for corners, mid in zip(mc_valid, mi_valid):
        mid_val = int(mid)
        idx = np.where(board_ids_ref.flatten() == mid_val)[0]
        if len(idx) == 0:
            continue
        for j in range(4):
            all_img_pts.append(corners[0][j])
            all_cids.append(mid_val * 4 + j)

    if len(all_img_pts) >= 6:
        return (np.array(all_img_pts, dtype=np.float32),
                np.array(all_cids, dtype=np.int32).reshape(-1, 1),
                mc, mi)
    return None, None, mc, mi


def detect_board_opencv4(gray):
    """OpenCV 4.x legacy Charuco detection."""
    mc, mi, _ = cv2.aruco.detectMarkers(gray, aruco_dict, parameters=detector_params)
    if mi is None or len(mi) < 4:
        return None, None, mc, mi
    n_c, cc, ci = cv2.aruco.interpolateCornersCharuco(mc, mi, gray, board)
    return cc, ci, mc, mi


def capture_loop():
    global rgb_frame, display_frame
    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YU12'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    print(f"Camera: {int(cap.get(3))}x{int(cap.get(4))} OK")

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.01)
            continue
        try:
            bgr = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
            with lock:
                rgb_frame = bgr
                display = cv2.resize(bgr, (640, 640))
                cv2.putText(display,
                    f"Captured: {len(calib_images)} | Show board & click Capture",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
                display_frame = display
        except Exception:
            time.sleep(0.01)
        time.sleep(0.03)


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ChArUco Calibration</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', sans-serif;
         display: flex; height: 100vh; }
  .left { flex: 1; display: flex; flex-direction: column; padding: 10px; }
  .right { width: 330px; padding: 16px; background: #161b22;
           border-left: 1px solid #30363d; overflow-y: auto; }
  .cam { flex: 1; display: flex; align-items: center; justify-content: center;
         background: #000; border-radius: 8px; overflow: hidden; }
  .cam img { max-width: 100%; max-height: 100%; }
  .bar { padding: 8px 0; display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
  h2 { font-size: 18px; margin-bottom: 10px; }
  h3 { font-size: 14px; margin: 16px 0 6px; color: #58a6ff; }
  button { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer;
           font-size: 13px; font-weight: bold; }
  .btn-capture { background: #238636; color: #fff; }
  .btn-capture:hover { background: #2ea043; }
  .btn-calib { background: #1f6feb; color: #fff; }
  .btn-calib:hover { background: #388bfd; }
  .btn-desk { background: #9c6ade; color: #fff; margin-top: 8px; }
  .btn-danger { background: #da3633; color: #fff; }
  .btn-danger:hover { background: #f85149; }
  .count { font-size: 24px; font-weight: bold; color: #3fb950; }
  .status { font-size: 13px; color: #8b949e; margin: 4px 0; }
  pre { background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
        padding: 12px; font-size: 12px; overflow-x: auto; color: #7ee787; }
  .info { font-size: 12px; color: #8b949e; margin: 4px 0; }
  input { background: #0d1117; color: #fff; border: 1px solid #30363d;
          padding: 4px 6px; border-radius: 4px; font-size: 12px; width: 70px; }
</style>
</head>
<body>
<div class="left">
  <div class="bar">
    <button class="btn-capture" onclick="capture()">📸 Capture</button>
    <button class="btn-calib" onclick="calibrate()">📐 Calibrate</button>
    <span class="count" id="count">0</span>
    <span style="font-size:13px;color:#8b949e;">imgs</span>
    <span id="msg" style="font-size:13px;color:#d2991d;"></span>
  </div>
  <div class="cam">
    <img src="/video_feed" id="stream">
  </div>
</div>
<div class="right">
  <h2>📐 ChArUco Calibration</h2>
  <div class="info">9×12 · squares 15mm · markers 11.25mm · DICT_5X5_100</div>
  <div class="status" id="status">Ready — show board to camera, then click Capture</div>

  <h3>Steps</h3>
  <div class="info">1. Capture 10–20 images from different angles</div>
  <div class="info">2. Click Calibrate (distortion only; intrinsics use device SEUCM)</div>

  <h3>Desktop Homography</h3>
  <div class="info">Place board flat on desk. Enter board origin in robot base frame:</div>
  <div class="info">X(m): <input id="dx" value="0.15"> &nbsp;Y(m): <input id="dy" value="0.0"></div>
  <button class="btn-desk" onclick="desktop()">🎯 Calibrate Desktop</button>

  <h3>Result</h3>
  <pre id="result">{{ result or 'Waiting...' }}</pre>

  <button class="btn-danger" onclick="reset()" style="margin-top:8px;">🗑 Clear All</button>
</div>

<script>
async function capture() {
  let resp = await fetch('/capture');
  let data = await resp.json();
  document.getElementById('count').textContent = data.count;
  document.getElementById('msg').textContent = data.msg;
  document.getElementById('status').textContent = data.status;
}
async function calibrate() {
  document.getElementById('status').textContent = 'Computing...';
  let resp = await fetch('/calibrate');
  let data = await resp.json();
  document.getElementById('result').textContent = data.result;
  document.getElementById('status').textContent = data.status;
  document.getElementById('msg').textContent = '';
}
async function desktop() {
  let x = document.getElementById('dx').value;
  let y = document.getElementById('dy').value;
  document.getElementById('status').textContent = 'Computing homography...';
  let resp = await fetch('/desktop?x=' + x + '&y=' + y);
  let data = await resp.json();
  document.getElementById('result').textContent = data.result;
  document.getElementById('status').textContent = data.status;
}
async function reset() {
  await fetch('/reset');
  document.getElementById('count').textContent = '0';
  document.getElementById('result').textContent = '';
  document.getElementById('status').textContent = 'Cleared';
  document.getElementById('msg').textContent = '';
}
</script>
</body>
</html>"""


def gen():
    while True:
        with lock:
            frame = display_frame.copy() if display_frame is not None else None
        if frame is not None:
            _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        time.sleep(0.05)


@app.route('/')
def index():
    return render_template_string(HTML, result=None)


@app.route('/video_feed')
def video_feed():
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/capture')
def capture():
    global calib_images
    with lock:
        frame = rgb_frame.copy() if rgb_frame is not None else None

    if frame is None:
        return jsonify(count=len(calib_images), msg="No frame",
                       status="Camera not ready")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if use_new_api:
        cc, ci, mc, mi = detect_board_opencv5(gray)
    else:
        cc, ci, mc, mi = detect_board_opencv4(gray)

    if mi is None or len(mi) < 4:
        return jsonify(count=len(calib_images),
                       msg="Detection failed! Ensure the full board is visible",
                       status=f"Markers: {len(mi) if mi else 0} (need ≥4)")

    if cc is None or ci is None:
        return jsonify(count=len(calib_images),
                       msg="Corner extraction failed",
                       status=f"Found {len(mi)} markers but corner extraction failed")

    calib_images.append((cc, ci))
    fname = os.path.join(SAVE_DIR, f"img_{len(calib_images):04d}.npz")
    np.savez(fname, corners=np.array(cc), ids=np.array(ci))

    n = len(calib_images)
    return jsonify(count=n,
                   msg=f"Saved! {len(cc)} corners",
                   status=f"Captured {n} images — 10–20 recommended before calibration")


@app.route('/calibrate')
def calibrate():
    global calib_images, calib_result

    if len(calib_images) < 5:
        return jsonify(result="", status=f"Need at least 5 images, have {len(calib_images)}")

    try:
        obj_points = []
        img_points = []

        for cc, ci in calib_images:
            obj_pts = []
            img_pts = []
            cc_arr = np.array(cc).reshape(-1, 2)
            ci_arr = np.array(ci).flatten()

            for i in range(len(cc_arr)):
                cid = int(ci_arr[i])
                mid_val = cid // 4
                corner_idx = cid % 4

                idx = np.where(board_ids_ref.flatten() == mid_val)
                if len(idx[0]) == 0:
                    continue
                obj_center = board_obj_points[idx[0][0]].flatten()

                half = MARKER_LENGTH / 2
                offsets = [(-half, -half), (half, -half), (half, half), (-half, half)]
                dx, dy = offsets[corner_idx]
                obj_pts.append([obj_center[0] + dx, obj_center[1] + dy, 0.0])
                img_pts.append(cc_arr[i])

            if len(obj_pts) >= 8:
                obj_points.append(np.array(obj_pts, dtype=np.float32).reshape(-1, 1, 3))
                img_points.append(np.array(img_pts, dtype=np.float32).reshape(-1, 1, 2))

        if len(obj_points) < 3:
            return jsonify(result="", status=f"Not enough valid images: {len(obj_points)} < 3")

        h, w = 1280, 1280
        total_pts = sum(len(p) for p in obj_points)

        # Device SEUCM intrinsics — fixed
        K_fixed = np.array([[392.168, 0, 637.761],
                            [0, 392.168, 640.597],
                            [0, 0, 1]], dtype=np.float64)

        # Fit distortion only
        ret, _, dist, _, _ = cv2.calibrateCamera(
            obj_points, img_points, (w, h), K_fixed, None,
            flags=cv2.CALIB_USE_INTRINSIC_GUESS | cv2.CALIB_FIX_INTRINSIC
        )
        D = dist.flatten()[:4]

        calib_result = {"K": K_fixed.tolist(), "D": D.tolist(), "rms": float(ret)}

        lines = [
            f"RMS: {ret:.4f}px  |  {len(obj_points)} images  |  {total_pts} points",
            "",
            "Intrinsics (device SEUCM, fixed):",
            "  fx=392.17  fy=392.17  u0=637.76  v0=640.60",
            "",
            "Distortion (from this calibration):",
            f"  D = {[f'{d:.6f}' for d in D]}",
            "",
            "Intrinsics use factory values — accurate enough.",
            "Next: place board flat on desk → Desktop Calibration",
        ]

        with open('/home/nieqingcao/calibration/charuco_calib_result.json', 'w') as f:
            json.dump(calib_result, f, indent=2)

        return jsonify(result="\n".join(lines),
                       status=f"Calibration done! RMS={ret:.4f}")

    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        return jsonify(result=f"Error: {str(e)}", status="Calibration failed — check server log")


@app.route('/desktop')
def desktop():
    global calib_images, desktop_result

    if len(calib_images) == 0:
        return jsonify(result="", status="Capture a desktop-flat image first")

    x = float(request.args.get('x', 0.15))
    y = float(request.args.get('y', 0.0))

    cc, ci = calib_images[-1]
    cc_arr = np.array(cc).reshape(-1, 2)
    ci_arr = np.array(ci).flatten()

    pixel_pts = []
    world_pts = []
    seen = set()

    for i in range(len(cc_arr)):
        mid = int(ci_arr[i]) // 4
        if mid in seen:
            continue
        seen.add(mid)

        idx = np.where(board_ids_ref.flatten() == mid)
        if len(idx[0]) == 0:
            continue
        obj_center = board_obj_points[idx[0][0]].flatten()

        wx = x + obj_center[0]
        wy = y + obj_center[1]
        px = cc_arr[i][0]
        py = cc_arr[i][1]

        pixel_pts.append([px, py])
        world_pts.append([wx, wy])

    if len(pixel_pts) < 4:
        return jsonify(result="", status=f"Not enough points: {len(pixel_pts)}")

    pixel_pts = np.array(pixel_pts, dtype=np.float32)
    world_pts = np.array(world_pts, dtype=np.float32)

    H, mask = cv2.findHomography(pixel_pts, world_pts, method=cv2.RANSAC)
    inliers = int(mask.sum()) if mask is not None else 0

    cp = np.array([640, 640, 1.0])
    cw = H @ cp
    cw = cw[:2] / cw[2]

    desktop_result = {"H": H.tolist(), "origin": [x, y, 0.0], "inliers": inliers}

    lines = [
        f"Desktop Homography ({inliers}/{len(pixel_pts)} inliers):",
        f"  H = [{H[0,0]:.4f}, {H[0,1]:.4f}, {H[0,2]:.4f}]",
        f"      [{H[1,0]:.4f}, {H[1,1]:.4f}, {H[1,2]:.4f}]",
        f"      [{H[2,0]:.4f}, {H[2,1]:.4f}, {H[2,2]:.4f}]",
        "",
        f"Verify: pixel center (640,640) → world ({cw[0]:.4f}, {cw[1]:.4f}) m",
        f"Board origin: ({x:.3f}, {y:.3f}, 0.0) m",
        "",
        "Copy H into transforms.calibrate_desktop_homography()",
    ]

    with open('/home/nieqingcao/calibration/desktop_calib_result.json', 'w') as f:
        json.dump(desktop_result, f, indent=2)

    return jsonify(result="\n".join(lines),
                   status=f"Desktop calibrated! {inliers} inliers")


@app.route('/reset')
def reset():
    global calib_images, calib_result, desktop_result
    calib_images = []
    calib_result = None
    desktop_result = None
    for f in os.listdir(SAVE_DIR):
        os.remove(os.path.join(SAVE_DIR, f))
    return jsonify(status="Cleared")


if __name__ == '__main__':
    t = threading.Thread(target=capture_loop, daemon=True)
    t.start()
    time.sleep(1.5)
    print("ChArUco Calibration: http://0.0.0.0:8081")
    app.run(host='0.0.0.0', port=8081, debug=False, threaded=True)
