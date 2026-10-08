"""
Object detection + coordinate mapping demo.
Put a single ArUco marker on your object → get robot base coordinates.
Usage:
  python demo_detect.py           # Single-shot detection
  python demo_detect.py --live    # Continuous detection with web stream
"""
import cv2
import numpy as np
import json
import time
import sys

# Load desktop homography
with open('/home/nieqingcao/calibration/desktop_calib_result.json') as f:
    data = json.load(f)
H = np.array(data['H'])
print(f"Loaded homography ({data['inliers']} inliers)")

# ArUco detector (single markers, DICT_5X5_100)
aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
aruco_detector = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())

# Camera
def open_camera():
    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YU12'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap

def read_frame(cap):
    ret, raw = cap.read()
    if not ret:
        return None
    return cv2.cvtColor(raw, cv2.COLOR_YUV2BGR_I420)

def pixel_to_world(u, v):
    """Map pixel to robot base XY using desktop homography."""
    p = np.array([u, v, 1.0])
    w = H @ p
    return float(w[0]/w[2]), float(w[1]/w[2])


def mode_single():
    """Single-shot: capture one frame and detect."""
    cap = open_camera()
    time.sleep(0.5)

    frame = read_frame(cap)
    cap.release()

    if frame is None:
        print("Failed to capture frame")
        return

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = aruco_detector.detectMarkers(gray)

    if ids is None:
        print("No ArUco markers detected. Put a DICT_5X5_100 marker on the object.")
        return

    print(f"\nDetected {len(ids)} marker(s):")
    for corner, mid in zip(corners, ids.flatten()):
        c = corner[0].mean(axis=0)
        cx, cy = int(c[0]), int(c[1])
        wx, wy = pixel_to_world(cx, cy)
        print(f"  ID={int(mid)}  pixel=({cx},{cy})  →  base=({wx:.4f}, {wy:.4f}) m")


def mode_live():
    """Continuous detection with web display."""
    from flask import Flask, Response, render_template_string

    app = Flask(__name__)
    display_frame = [None]
    lock = __import__('threading').Lock()

    def capture_loop():
        cap = open_camera()
        while True:
            frame = read_frame(cap)
            if frame is None:
                time.sleep(0.01)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            corners, ids, _ = aruco_detector.detectMarkers(gray)

            if ids is not None:
                cv2.aruco.drawDetectedMarkers(frame, corners, ids)
                for corner, mid in zip(corners, ids.flatten()):
                    c = corner[0].mean(axis=0)
                    cx, cy = int(c[0]), int(c[1])
                    wx, wy = pixel_to_world(cx, cy)
                    label = f"ID:{int(mid)} ({wx:.3f},{wy:.3f})m"
                    cv2.putText(frame, label, (cx-40, cy-20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)

            disp = cv2.resize(frame, (640, 640))
            with lock:
                display_frame[0] = disp
            time.sleep(0.05)

    HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ArUco Detection</title>
<style>
body{margin:0;background:#111;display:flex;justify-content:center;align-items:center;
     min-height:100vh;font-family:Segoe UI,sans-serif}
h2{color:#4f9}img{max-width:95vw;max-height:90vh;border:2px solid #333;border-radius:8px}
</style></head>
<body><div style="text-align:center">
<h2>ArUco Object Detection — DICT_5X5_100</h2>
<img src="/video_feed"></div></body></html>"""

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

    import threading
    threading.Thread(target=capture_loop, daemon=True).start()
    time.sleep(1)
    print("\nOpen: http://192.168.58.68:8082")
    app.run(host='0.0.0.0', port=8082, debug=False, threaded=True)


if __name__ == '__main__':
    if '--live' in sys.argv:
        mode_live()
    else:
        mode_single()
