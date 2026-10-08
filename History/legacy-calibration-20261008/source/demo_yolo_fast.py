"""
YOLO live detection — optimized for CPU.
  640x640 inference, 2fps detection, smooth stream.
  http://<IP>:8084
"""
import cv2, numpy as np, json, time, sys, threading as th
from flask import Flask, Response, render_template_string, jsonify
from ultralytics import YOLO

with open('/home/nieqingcao/calibration/desktop_calib_result.json') as f:
    H = np.array(json.load(f)['H'])

def p2w(u, v):
    p = np.array([u, v, 1.0])
    w = H @ p
    return float(w[0]/w[2]), float(w[1]/w[2])

def estimate_z(box_w, box_h):
    """Estimate object height from bounding box size.
    Larger box = closer to camera = taller object.
    Calibrated: a 50mm object at table level is ~200px at 1280x1280 @ 220° FOV.
    """
    # Simple heuristic: box area relative to frame area
    box_area = box_w * box_h
    frame_area = 1280 * 1280
    ratio = box_area / frame_area

    # Map to approximate Z in meters (table=0, camera at ~0.5m above)
    # Small box → far away → low Z. Large box → close → higher Z.
    if ratio > 0.01:
        z_m = ratio * 2.0  # ~0.02-0.20m estimated height
    else:
        z_m = 0.02
    return round(z_m, 3)

model = YOLO('yolov8n.pt')
model.to('cpu')
print(f"YOLOv8n ready, {len(model.names)} classes")

app = Flask(__name__)
display = [None]
objects = [[]]
lock = th.Lock()

def capture_loop():
    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YU12'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    tick = 0
    last_objs = []

    while True:
        ret, raw = cap.read()
        if not ret:
            time.sleep(0.01)
            continue
        frame = cv2.cvtColor(raw, cv2.COLOR_YUV2BGR_I420)
        tick += 1

        # YOLO every 15 frames (~2fps at 30fps capture)
        if tick % 15 == 0:
            small = cv2.resize(frame, (640, 640))
            results = model(small, conf=0.3, verbose=False, imgsz=640)
            objs = []
            for r in results:
                if r.boxes is None:
                    continue
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    conf_val = float(box.conf[0])
                    xyxy = box.xyxy[0].cpu().numpy()
                    x1, y1, x2, y2 = map(int, xyxy * 2)  # scale back to 1280
                    cx, cy = (x1+x2)//2, (y1+y2)//2
                    bw, bh = x2-x1, y2-y1
                    label = model.names.get(cls_id, f'cls{cls_id}')
                    wx, wy = p2w(cx, cy)
                    wz = estimate_z(bw, bh)
                    objs.append((label, cx, cy, wx, wy, wz, conf_val, x1, y1, x2, y2))
            last_objs = objs

        # Draw
        out = cv2.resize(frame, (640, 640))
        for i, (label, cx, cy, wx, wy, wz, conf_val, x1, y1, x2, y2) in enumerate(last_objs):
            sx1, sy1 = x1//2, y1//2
            sx2, sy2 = x2//2, y2//2
            scx, scy = cx//2, cy//2
            cv2.rectangle(out, (sx1, sy1), (sx2, sy2), (0, 255, 0), 2)
            cv2.putText(out, f"{label} ({wx:.3f},{wy:.3f},{wz:.3f})m",
                        (sx1, max(sy1-6, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            cv2.circle(out, (scx, scy), 3, (0, 255, 0), -1)

        cv2.putText(out, f"YOLOv8n | {len(last_objs)} objects | CPU",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        with lock:
            display[0] = out
            objects[0] = last_objs
        time.sleep(0.03)

HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>YOLO Detection</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,sans-serif;display:flex;height:100vh}
.l{flex:1;display:flex;align-items:center;justify-content:center;padding:8px}
.l img{max-width:100%;max-height:98vh;border:2px solid #30363d;border-radius:8px}
.r{width:260px;padding:14px;background:#161b22;overflow-y:auto;border-left:1px solid #30363d}
h2{color:#58a6ff;font-size:15px;margin-bottom:8px}
.o{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;margin:6px 0;font-size:12px}
.o .n{color:#3fb950;font-weight:bold}
.o .d{color:#8b949e;font-size:11px}
.o .c{color:#7ee787;font-size:11px}
.bar{height:3px;background:#30363d;border-radius:2px;margin-top:3px}
.bar div{height:3px;background:#3fb950;border-radius:2px}
</style></head>
<body>
<div class="l"><img src="/video_feed"></div>
<div class="r">
<h2>YOLOv8n — 80 Classes</h2>
<div style="font-size:11px;color:#8b949e;margin-bottom:8px" id="info">Ready</div>
<div id="list"></div>
</div>
<script>
setInterval(async()=>{
  let r=await fetch('/objects');let d=await r.json();
  document.getElementById('info').textContent=d.count+' objects';
  let h='';
  for(let o of d.objects){
    h+=`<div class="o">
      <span class="n">${o.label}</span> <span class="d">${o.conf}</span>
      <div class="c">base (${o.wx}, ${o.wy}, z≈${o.wz})m</div>
      <div class="bar"><div style="width:${(o.conf*100)|0}%"></div></div>
    </div>`;
  }
  document.getElementById('list').innerHTML=h||'<div class="d">No objects</div>';
},800);
</script></body></html>"""

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
    objs = objects[0]
    return jsonify({"count": len(objs), "objects": [
        {"label": o[0], "cx": o[1], "cy": o[2],
         "wx": f"{o[3]:.4f}", "wy": f"{o[4]:.4f}", "wz": f"{o[5]:.3f}",
         "conf": f"{o[6]:.2f}"}
        for o in objs[:12]
    ]})

if __name__ == '__main__':
    th.Thread(target=capture_loop, daemon=True).start()
    time.sleep(4)
    print("Open: http://192.168.58.68:8084")
    app.run(host='0.0.0.0', port=8084, debug=False, threaded=True)
