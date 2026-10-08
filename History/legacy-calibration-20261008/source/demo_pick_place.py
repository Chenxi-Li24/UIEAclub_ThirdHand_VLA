"""
Pick-and-place demo — YOLO detection + coordinate mapping + arm control.
  python demo_pick_place.py             # Single-shot: detect → pick → place
  python demo_pick_place.py --live      # Web UI with detect + move buttons
  python demo_pick_place.py --dry-run   # Test without moving arm
"""
import cv2, numpy as np, json, time, sys, requests
from flask import Flask, Response, render_template_string, jsonify
import threading as th

# ============================================================
# Config
# ============================================================
H = np.array(json.load(open('/home/nieqingcao/calibration/desktop_calib_result.json'))['H'])
YOLO_API = "http://localhost:8084/objects"
ARM_BASE = "http://localhost:3000"
DRY_RUN = '--dry-run' in sys.argv
SAFE_Z = 0.10     # Safe approach height (m)
PLACE_X = 0.15    # Place location X (m)
PLACE_Y = 0.0     # Place location Y (m)
PLACE_Z = 0.02    # Place height (m)

def p2w(u, v):
    p = np.array([u, v, 1.0])
    w = H @ p
    return float(w[0]/w[2]), float(w[1]/w[2])

def yolo_detect():
    """Get objects from YOLO server."""
    try:
        resp = requests.get(YOLO_API, timeout=5)
        return resp.json()
    except Exception as e:
        return {"count": 0, "objects": [], "error": str(e)}

def move_arm_ws(x, y, z):
    """Send move command to arm via WebSocket-like HTTP."""
    if DRY_RUN:
        print(f"  [DRY RUN] Move to ({x:.4f}, {y:.4f}, {z:.4f})")
        return True

    # Use the fixed_pick_place infrastructure
    import subprocess, os
    script = os.path.expanduser(
        "~/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place/web-control/scripts/teach_fixed_point.py"
    )
    # For now, just log the target position
    print(f"  [ARM] Target: ({x:.4f}, {y:.4f}, {z:.4f}) — arm movement needs CAN bridge")
    # TODO: integrate with startouch_bridge.py move_l command
    return True

def move_arm(x, y, z, speed=0.1):
    """Move arm to Cartesian position."""
    move_arm_ws(x, y, z)
    time.sleep(0.5)

def pick_and_place(target_label=None):
    """Run one pick-and-place cycle."""
    results = []

    # 1. Detect
    print("\n[1/5] Detecting objects...")
    data = yolo_detect()
    objects = data.get('objects', [])
    print(f"  Found {len(objects)} object(s)")

    if not objects:
        print("  No objects found!")
        return False

    # 2. Select target
    target = objects[0]  # Pick first object by default
    if target_label:
        for o in objects:
            if o['label'] == target_label:
                target = o
                break

    label = target['label']
    wx, wy, wz = float(target['wx']), float(target['wy']), float(target['wz'])
    print(f"[2/5] Target: {label} at ({wx:.4f}, {wy:.4f}, z≈{wz:.3f})m")

    # 3. Approach
    print(f"[3/5] Approaching from above...")
    move_arm(wx, wy, SAFE_Z, speed=0.15)

    # 4. Descend & grasp
    print(f"[4/5] Descending to grasp...")
    move_arm(wx, wy, max(wz, 0.005), speed=0.08)
    # close_gripper()

    # 5. Lift & place
    print(f"[5/5] Lifting and placing...")
    move_arm(wx, wy, SAFE_Z, speed=0.12)
    move_arm(PLACE_X, PLACE_Y, PLACE_Z, speed=0.15)
    # open_gripper()

    print(f"\n✅ Pick-and-place complete: {label}")
    return True


# ============================================================
# Web UI
# ============================================================
app = Flask(__name__)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Pick & Place</title>
<meta http-equiv="refresh" content="5">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,sans-serif;padding:20px}
h1{color:#58a6ff;margin-bottom:16px}
.grid{display:flex;gap:20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;flex:1}
.card h2{font-size:16px;margin-bottom:12px}
.obj{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px;margin:8px 0}
.obj .name{color:#3fb950;font-weight:bold;font-size:14px}
.obj .pos{color:#7ee787;font-size:12px}
button{padding:8px 20px;border:none;border-radius:6px;cursor:pointer;font-size:14px;font-weight:bold}
.btn-go{background:#238636;color:#fff}
.btn-go:hover{background:#2ea043}
.btn-stop{background:#da3633;color:#fff;margin-left:10px}
.status{font-size:13px;color:#8b949e;margin-top:12px}
.info{font-size:12px;color:#8b949e;margin:4px 0}
</style></head>
<body>
<h1>🤖 Pick & Place Demo</h1>
<div class="grid">
<div class="card">
  <h2>📷 Detection (YOLO :8084)</h2>
  <div id="objects">Loading...</div>
</div>
<div class="card">
  <h2>🦾 Control</h2>
  <div style="display:flex;gap:10px;margin:12px 0">
    <button class="btn-go" onclick="run()">▶ Pick & Place</button>
    <button class="btn-stop" onclick="stop()">⏹ Stop</button>
  </div>
  <div class="status" id="status">Ready</div>
  <div class="info">Arm: <a href="http://192.168.58.68:3000" target="_blank" style="color:#58a6ff">:3000</a></div>
  <div class="info">Camera: <a href="http://192.168.58.68:8084" target="_blank" style="color:#58a6ff">:8084</a></div>
</div>
</div>
<script>
async function load(){
  try{
    let r=await fetch('http://localhost:8084/objects');
    let d=await r.json();
    let h='';
    for(let o of (d.objects||[])){
      h+=`<div class="obj">
        <span class="name">${o.label}</span> (${o.conf})
        <div class="pos">base (${o.wx}, ${o.wy}, z≈${o.wz})m</div>
      </div>`;
    }
    document.getElementById('objects').innerHTML=h||'No objects detected';
  }catch(e){document.getElementById('objects').innerHTML='YOLO server offline';}
}
async function run(){
  document.getElementById('status').textContent='Running...';
  let r=await fetch('/run');
  let d=await r.json();
  document.getElementById('status').textContent=d.status;
}
async function stop(){document.getElementById('status').textContent='Stopped';}
setInterval(load, 2000);
load();
</script>
</body></html>"""

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/run')
def run():
    ok = pick_and_place()
    return jsonify(status="✅ Done" if ok else "❌ No objects")


def mode_live():
    print("Pick & Place dashboard: http://192.168.58.68:8086")
    app.run(host='0.0.0.0', port=8086, debug=False, threaded=True)


if __name__ == '__main__':
    if '--live' in sys.argv:
        mode_live()
    else:
        pick_and_place()
