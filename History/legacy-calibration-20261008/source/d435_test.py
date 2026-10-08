"""
D435 test — verify camera streams RGB + aligned depth.
  http://<IP>:8090

Usage:
  python d435_test.py
"""
import numpy as np
import cv2
import time
import threading
import pyrealsense2 as rs
from flask import Flask, Response, render_template_string

app = Flask(__name__)

# Shared state
rgb_frame = None
depth_colormap = None
depth_raw = None
frame_lock = threading.Lock()
running = True

INDEX = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>D435 Test</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,sans-serif;display:flex;flex-direction:column;height:100vh}
.header{padding:10px 20px;background:#161b22;border-bottom:1px solid #30363d;display:flex;justify-content:space-between;align-items:center}
.header h2{font-size:16px}
.main{flex:1;display:flex;gap:4px;padding:4px}
.panel{flex:1;display:flex;flex-direction:column;background:#0d1117;border:1px solid #30363d;border-radius:6px;overflow:hidden}
.panel-title{padding:8px 16px;background:#161b22;font-size:14px;font-weight:bold;border-bottom:1px solid #30363d}
.panel-body{flex:1;display:flex;align-items:center;justify-content:center;background:#000}
.panel-body img{max-width:100%;max-height:100%;object-fit:contain}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.dot.green{background:#3fb950}.dot.blue{background:#58a6ff}
</style></head><body>
<div class="header">
<h2><span class="dot green"></span>D435 RGB-D Test</h2>
<div><span class="dot blue"></span>RGB 640×480 | Depth 640×480</div>
</div>
<div class="main">
<div class="panel">
<div class="panel-title">RGB</div>
<div class="panel-body"><img src="/rgb"></div>
</div>
<div class="panel">
<div class="panel-title">Depth (JET colormap, 0-3m)</div>
<div class="panel-body"><img src="/depth"></div>
</div>
</div>
</body></html>"""


def capture_loop():
    """D435 pipeline: RGB + aligned depth."""
    global rgb_frame, depth_colormap, depth_raw, running

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

    try:
        profile = pipeline.start(config)
    except Exception as e:
        print(f"❌ Failed to start D435: {e}")
        print("  Make sure D435 is on a USB 3.0 (blue) port!")
        running = False
        return

    # Get depth scale (mm → meters)
    depth_sensor = profile.get_device().first_depth_sensor()
    depth_scale = depth_sensor.get_depth_scale()
    print(f"D435: depth scale = {depth_scale:.4f} (mm→m)")

    # Align depth to color
    align = rs.align(rs.stream.color)

    # Warm up
    for _ in range(30):
        pipeline.wait_for_frames()

    print("D435 streaming started. http://0.0.0.0:8090")
    frame_count = 0

    try:
        while running:
            frames = pipeline.wait_for_frames()
            aligned = align.process(frames)

            color_frame = aligned.get_color_frame()
            depth_frame = aligned.get_depth_frame()

            if not color_frame or not depth_frame:
                continue

            # RGB
            rgb = np.asanyarray(color_frame.get_data())

            # Depth: uint16 mm → colormap
            depth_data = np.asanyarray(depth_frame.get_data())
            depth_clip = np.clip(depth_data, 0, 3000).astype(np.float32)
            depth_clip = (depth_clip / 3000.0 * 255).astype(np.uint8)
            depth_color = cv2.applyColorMap(depth_clip, cv2.COLORMAP_JET)
            depth_color[depth_data == 0] = [0, 0, 0]

            with frame_lock:
                rgb_frame = rgb.copy()
                depth_colormap = depth_color
                depth_raw = depth_data.copy()

            frame_count += 1
            if frame_count == 30:
                d_center = depth_data[240, 320] * depth_scale
                d_valid = depth_data[depth_data > 0]
                pct = len(d_valid) / depth_data.size * 100
                print(f"Frame {frame_count}: center depth={d_center:.3f}m, "
                      f"valid={pct:.1f}%", flush=True)

    except Exception as e:
        print(f"D435 capture error: {e}")
    finally:
        pipeline.stop()
        print("D435 pipeline stopped.")


def gen_rgb():
    global rgb_frame
    while running:
        with frame_lock:
            f = rgb_frame.copy() if rgb_frame is not None else None
        if f is not None:
            _, jpg = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' +
                   jpg.tobytes() + b'\r\n')
        time.sleep(0.03)


def gen_depth():
    global depth_colormap
    while running:
        with frame_lock:
            f = depth_colormap.copy() if depth_colormap is not None else None
        if f is not None:
            _, jpg = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' +
                   jpg.tobytes() + b'\r\n')
        time.sleep(0.03)


@app.route('/')
def index():
    return render_template_string(INDEX)


@app.route('/rgb')
def rgb_stream():
    return Response(gen_rgb(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/depth')
def depth_stream():
    return Response(gen_depth(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == '__main__':
    t = threading.Thread(target=capture_loop, daemon=True)
    t.start()
    time.sleep(2)

    if running:
        app.run(host='0.0.0.0', port=8090, debug=False, threaded=True)
    else:
        print("Camera init failed. Check USB connection.")
