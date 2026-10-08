"""
Pure visual grasping — YOLO + SEUCM desk plane intersection.
No depth sensor, no SLAM, no markers on objects.

Camera model: SEUCM (α=0.679, β=0.749, fx=392.17)
Desk plane: known Z height, camera fixed above

  pixel → SEUCM unproject → camera ray
  ray ∩ Z=desk_height plane → (X,Y,Z) in camera frame
  T_base_camera → (X,Y,Z) in robot base frame
"""
import cv2, numpy as np, json, time, sys, threading as th
from flask import Flask, Response, render_template_string, jsonify
from ultralytics import YOLO

# ============================================================
# SEUCM camera model (Lumos Touch R1 onboard camera)
# ============================================================
FX, FY = 392.168, 392.168
U0, V0 = 637.761, 640.597
ALPHA = 0.678979
BETA = 0.749026
W, H = 1280, 1280

# ============================================================
# Desk plane & camera pose
# ============================================================
# Homography from Charuco calibration (pixel → desk XY)
with open('/home/nieqingcao/calibration/desktop_calib_result.json') as f:
    H_mat = np.array(json.load(f)['H'])
DESK_Z = 0.0  # Desk height in robot base frame (meters)

# ============================================================
# SEUCM projection
# ============================================================
def unproject(u, v):
    """Pixel → unit direction vector in camera frame (SEUCM)."""
    xn = (u - U0) / FX
    yn = (v - V0) / FY
    r2 = xn*xn + yn*yn

    a2 = ALPHA * ALPHA
    a2b = a2 - BETA

    if a2b > 0 and r2 >= 1.0 / a2b:
        return None  # Outside valid projection area

    sqrt_term = np.sqrt(max(1 - a2b * r2, 0))
    denom = ALPHA * sqrt_term + (1 - ALPHA)
    if denom < 1e-10:
        return None

    Z = (1 - a2 * BETA * r2) / denom
    norm = np.sqrt(xn*xn + yn*yn + Z*Z)
    if norm < 1e-10:
        return None

    return np.array([xn/norm, yn/norm, Z/norm])


def pixel_to_camera_plane(u, v, plane_z=0.0):
    """Pixel → 3D point in camera frame by intersecting ray with Z=plane_z plane."""
    ray = unproject(u, v)
    if ray is None or ray[2] <= 1e-10:
        return None  # Ray points upward or parallel to desk
    scale = plane_z / ray[2]
    return ray * scale


def pixel_to_base(u, v):
    """Pixel → robot base XY via Charuco homography. Z=DESK_Z (table plane)."""
    p = np.array([u, v, 1.0])
    w = H_mat @ p
    wx, wy = float(w[0]/w[2]), float(w[1]/w[2])
    return np.array([wx, wy, DESK_Z])


# ============================================================
# YOLO model
# ============================================================
model = YOLO('yolov8n.pt')
model.to('cpu')

# ============================================================
# Camera capture
# ============================================================
def open_cam():
    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YU12'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


# ============================================================
# Flask app
# ============================================================
app = Flask(__name__)
display = [None]
objects = [[]]
lock = th.Lock()

def capture_loop():
    cap = open_cam()
    tick = 0
    last_objs = []

    while True:
        ret, raw = cap.read()
        if not ret:
            time.sleep(0.01); continue
        frame = cv2.cvtColor(raw, cv2.COLOR_YUV2BGR_I420)
        tick += 1

        # YOLO every 15 frames (~2fps) — bottle only
        if tick % 15 == 0:
            small = cv2.resize(frame, (640, 640))
            results = model(small, conf=0.25, verbose=False, imgsz=640,
                           classes=[39])  # 39 = bottle
            objs = []
            for r in results:
                if r.boxes is None: continue
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    conf_val = float(box.conf[0])
                    xyxy = box.xyxy[0].cpu().numpy()
                    x1,y1,x2,y2 = map(int, xyxy * 2)
                    cx,cy = (x1+x2)//2, (y1+y2)//2
                    label = model.names.get(cls_id, f'cls{cls_id}')

                    # Map to base
                    pt_base = pixel_to_base(cx, cy)
                    if pt_base is not None:
                        bx, by, bz = pt_base
                    else:
                        bx, by, bz = 0, 0, 0

                    objs.append((label, cx, cy, bx, by, bz, conf_val, x1, y1, x2, y2))
            last_objs = objs

        # Draw
        out = cv2.resize(frame, (640, 640))
        for (label, cx, cy, bx, by, bz, cf, x1, y1, x2, y2) in last_objs:
            sx1, sy1, sx2, sy2 = x1//2, y1//2, x2//2, y2//2
            scx, scy = cx//2, cy//2
            cv2.rectangle(out, (sx1, sy1), (sx2, sy2), (0, 255, 0), 2)
            cv2.putText(out, f"{label} ({bx:.3f},{by:.3f},{bz:.3f})m",
                        (sx1, max(sy1-6, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            cv2.circle(out, (scx, scy), 3, (0, 255, 0), -1)

        cv2.putText(out, f"Bottle Grasp | {len(last_objs)} found",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        with lock:
            display[0] = out
            objects[0] = last_objs
        time.sleep(0.03)


HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Visual Grasp</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,sans-serif;display:flex;height:100vh}
.l{flex:1;display:flex;align-items:center;justify-content:center;padding:8px}
.l img{max-width:100%;max-height:98vh;border:2px solid #30363d;border-radius:8px}
.r{width:280px;padding:14px;background:#161b22;overflow-y:auto;border-left:1px solid #30363d}
h2{color:#58a6ff;font-size:15px;margin-bottom:6px}
.tag{font-size:10px;color:#8b949e;margin-bottom:8px}
.o{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;margin:6px 0;font-size:12px}
.o .n{color:#3fb950;font-weight:bold}
.o .c{color:#7ee787;font-size:11px}
.o .m{color:#d2991d;font-size:10px}
.bar{height:3px;background:#30363d;border-radius:2px;margin-top:3px}
.bar div{height:3px;background:#3fb950;border-radius:2px}
.btn{display:inline-block;padding:6px 14px;background:#238636;color:#fff;border:none;
     border-radius:6px;cursor:pointer;font-size:13px;font-weight:bold;margin:4px 2px}
.btn:hover{background:#2ea043}
</style></head>
<body>
<div class="l"><img src="/video_feed"></div>
<div class="r">
<h2>🍾 Bottle Grasp</h2>
<div class="tag">YOLOv8n — bottle only (class 39)</div>
<div id="info" style="font-size:11px;color:#8b949e">Ready</div>
<div id="list"></div>
<div style="margin-top:10px">
  <button class="btn" onclick="pick(0)">🎯 Pick First</button>
</div>
</div>
<script>
setInterval(async()=>{
  let r=await fetch('/objects');let d=await r.json();
  document.getElementById('info').textContent=d.count+' objects';
  let h='';
  for(let i=0;i<d.objects.length;i++){
    let o=d.objects[i];
    h+=`<div class="o">
      <span class="n">${o.label}</span> <span style="color:#8b949e;font-size:11px">${o.conf}</span>
      <div class="c">base (${o.bx}, ${o.by}, ${o.bz})m</div>
      <div class="m">SEUCM ray→desk Z=0</div>
      <div class="bar"><div style="width:${(o.conf*100)|0}%"></div></div>
    </div>`;
  }
  document.getElementById('list').innerHTML=h||'<div style="color:#8b949e">No objects</div>';
},800);
async function pick(i){
  let r=await fetch('/pick?i='+i);let d=await r.json();
  alert(d.status);
}
</script>
</body></html>"""

@app.route('/')
def index():
    return render_template_string(HTML)

def gen():
    while True:
        with lock:
            f = display[0].copy() if display[0] is not None else None
        if f is not None:
            _, jpg = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+jpg.tobytes()+b'\r\n')
        time.sleep(0.04)

@app.route('/video_feed')
def video_feed():
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/objects')
def get_objects():
    return jsonify({"count": len(objects[0]), "objects": [
        {"label": o[0], "cx": o[1], "cy": o[2],
         "bx": f"{o[3]:.4f}", "by": f"{o[4]:.4f}", "bz": f"{o[5]:.3f}",
         "conf": f"{o[6]:.2f}"}
        for o in objects[0][:12]
    ]})

@app.route('/pick')
def pick():
    i = int(request.args.get('i', 0))
    objs = objects[0]
    if i >= len(objs):
        return jsonify(status="No such object")
    o = objs[i]
    bx, by, bz = o[3], o[4], o[5]
    return jsonify(status=f"Target: {o[0]} at ({bx:.4f},{by:.4f},{bz:.3f})m — ready to grasp")


if __name__ == '__main__':
    th.Thread(target=capture_loop, daemon=True).start()
    time.sleep(4)
    print("Visual Grasp: http://192.168.58.68:8088")
    app.run(host='0.0.0.0', port=8088, debug=False, threaded=True)
