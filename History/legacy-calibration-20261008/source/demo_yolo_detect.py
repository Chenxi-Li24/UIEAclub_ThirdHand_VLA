"""
YOLO object detection + coordinate mapping.
Detects 80 COCO classes, maps center to robot base via desktop homography.
Usage:
  python demo_yolo_detect.py              # Single-shot test
  python demo_yolo_detect.py --live       # Web stream with real-time detection
"""
import cv2
import numpy as np
import json
import time
import sys
import threading as th

from ultralytics import YOLO

# Load homography
with open('/home/nieqingcao/calibration/desktop_calib_result.json') as f:
    H = np.array(json.load(f)['H'])

def pixel_to_world(u, v):
    p = np.array([u, v, 1.0])
    w = H @ p
    return float(w[0]/w[2]), float(w[1]/w[2])

# Load model (lazy)
model = None

def get_model():
    global model
    if model is None:
        model = YOLO('yolov8n.pt')
        print(f"YOLOv8n loaded: {len(model.names)} classes")
    return model

# Camera
def open_camera():
    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YU12'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FPS, 60)
    return cap

def read_frame(cap):
    ret, raw = cap.read()
    if not ret:
        return None
    return cv2.cvtColor(raw, cv2.COLOR_YUV2BGR_I420)


COLORS = [
    (0, 255, 0), (255, 200, 0), (0, 200, 255), (255, 0, 200),
    (200, 255, 0), (0, 255, 200), (255, 100, 100), (100, 255, 100),
]


def detect_and_draw(frame, conf=0.35):
    """Run YOLO, draw results, return list of (label, cx, cy, wx, wy, conf)."""
    m = get_model()
    results = m(frame, conf=conf, verbose=False, imgsz=640)

    objects = []
    for r in results:
        boxes = r.boxes
        if boxes is None:
            continue
        for i, box in enumerate(boxes):
            cls_id = int(box.cls[0])
            conf_val = float(box.conf[0])
            xyxy = box.xyxy[0].cpu().numpy()
            x1, y1, x2, y2 = map(int, xyxy)
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            label = m.names.get(cls_id, f'cls{cls_id}')
            wx, wy = pixel_to_world(cx, cy)

            objects.append((label, cx, cy, wx, wy, conf_val, (x1, y1, x2, y2)))

    # Draw
    out = frame.copy()
    for i, (label, cx, cy, wx, wy, conf_val, (x1, y1, x2, y2)) in enumerate(objects):
        color = COLORS[i % len(COLORS)]
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        text = f"{label} ({wx:.3f},{wy:.3f})m"
        cv2.putText(out, text, (x1, max(y1-8, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        cv2.circle(out, (cx, cy), 4, color, -1)

    return out, objects


def mode_single():
    cap = open_camera()
    time.sleep(0.5)
    frame = read_frame(cap)
    cap.release()

    if frame is None:
        print("Camera error")
        return

    out, objects = detect_and_draw(frame, conf=0.3)
    cv2.imwrite('/tmp/yolo_detect.jpg', out)
    print(f"\nDetected {len(objects)} object(s):")
    for label, cx, cy, wx, wy, conf_val, _ in objects:
        print(f"  {label:15s} conf={conf_val:.2f}  pixel=({cx},{cy})  →  base=({wx:.4f},{wy:.4f})m")
    print(f"\nSaved /tmp/yolo_detect.jpg")


def mode_live():
    from flask import Flask, Response, render_template_string

    app = Flask(__name__)
    display_frame = [None]
    last_objects = [[]]
    lock = th.Lock()

    def loop():
        cap = open_camera()
        while True:
            frame = read_frame(cap)
            if frame is None:
                time.sleep(0.01)
                continue

            out, objects = detect_and_draw(frame, conf=0.3)

            disp = cv2.resize(out, (640, 640))
            cv2.putText(disp, f"YOLOv8n | Objects: {len(objects)}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
            with lock:
                display_frame[0] = disp
                last_objects[0] = objects
            time.sleep(0.1)

    HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>YOLO Detection</title>
<style>
body{margin:0;background:#111;display:flex;font-family:Segoe UI,sans-serif;height:100vh}
.left{flex:1;display:flex;align-items:center;justify-content:center;padding:10px}
.left img{max-width:100%;max-height:95vh;border:2px solid #333;border-radius:8px}
.right{width:280px;padding:16px;background:#161b22;color:#c9d1d9;overflow-y:auto;
       border-left:1px solid #30363d}
h2{color:#58a6ff;font-size:16px;margin:0 0 10px}
.obj{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;margin:6px 0;
     font-size:12px}
.obj .name{color:#3fb950;font-weight:bold}
.obj .pos{color:#8b949e}
.obj .coord{color:#7ee787}
.confbar{height:3px;background:#30363d;border-radius:2px;margin-top:4px}
.confbar div{height:3px;background:#3fb950;border-radius:2px}
</style></head>
<body>
<div class="left"><img src="/video_feed"></div>
<div class="right">
<h2>YOLOv8n — 80 Classes</h2>
<div id="info" style="font-size:11px;color:#8b949e">Loading model...</div>
<div id="objects"></div>
</div>
<script>
setInterval(async()=>{
  let r=await fetch('/objects');let d=await r.json();
  document.getElementById('info').textContent=d.count+' objects detected';
  let h='';
  for(let o of d.objects){
    h+=`<div class="obj">
      <span class="name">${o.label}</span> <span class="pos">conf:${o.conf}</span><br>
      <span class="coord">pixel(${o.cx},${o.cy}) → base(${o.wx},${o.wy})m</span>
      <div class="confbar"><div style="width:${(o.conf*100)|0}%"></div></div>
    </div>`;
  }
  document.getElementById('objects').innerHTML=h||'<div style="color:#8b949e">No objects</div>';
},500);
</script></body></html>"""

    @app.route('/')
    def index():
        return render_template_string(HTML)

    def gen():
        while True:
            with lock:
                f = display_frame[0].copy() if display_frame[0] is not None else None
            if f is not None:
                _, jpg = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 75])
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+jpg.tobytes()+b'\r\n')
            time.sleep(0.05)

    @app.route('/video_feed')
    def video_feed():
        return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

    @app.route('/objects')
    def objects_api():
        objs = last_objects[0]
        return jsonify({
            "count": len(objs),
            "objects": [{
                "label": o[0], "cx": o[1], "cy": o[2],
                "wx": f"{o[3]:.4f}", "wy": f"{o[4]:.4f}",
                "conf": f"{o[5]:.2f}"
            } for o in objs[:15]]
        })

    th.Thread(target=loop, daemon=True).start()
    time.sleep(3)
    print("\nOpen: http://192.168.58.68:8084")
    app.run(host='0.0.0.0', port=8084, debug=False, threaded=True)


if __name__ == '__main__':
    if '--live' in sys.argv:
        mode_live()
    else:
        mode_single()
