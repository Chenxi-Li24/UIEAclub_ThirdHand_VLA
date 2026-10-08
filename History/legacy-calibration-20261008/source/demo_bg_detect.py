"""
Background-subtraction object detection — no markers, no models.
  1. Capture empty desk as background
  2. Place object → auto-detect its position in robot coordinates
Usage:
  python demo_bg_detect.py              # Single-shot: capture bg, then detect
  python demo_bg_detect.py --live       # Web stream with real-time detection
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

def pixel_to_world(u, v):
    p = np.array([u, v, 1.0])
    w = H @ p
    return float(w[0]/w[2]), float(w[1]/w[2])


class BackgroundDetector:
    """Detect foreground objects using background subtraction."""

    def __init__(self):
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=36, detectShadows=False
        )
        self.bg_captured = False
        self.bg_image = None

    def capture_background(self, frame):
        """Learn the background from current frame."""
        self.bg_image = frame.copy()
        # Feed several frames to learn background
        for _ in range(30):
            self.bg_subtractor.apply(frame)
        self.bg_captured = True
        print("Background captured")

    def detect(self, frame):
        """Detect foreground objects. Returns list of (center_x, center_y, contour_area)."""
        if not self.bg_captured:
            return []

        fg_mask = self.bg_subtractor.apply(frame, learningRate=0)

        # Clean up
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel, iterations=2)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel, iterations=3)

        # Find contours
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        objects = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 500:  # filter noise
                continue
            M = cv2.moments(cnt)
            if M["m00"] < 1:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            objects.append((cx, cy, area, cnt))

        # Sort by area descending (largest first)
        objects.sort(key=lambda x: x[2], reverse=True)
        return objects

    def draw(self, frame, objects):
        """Draw detected objects on frame."""
        out = frame.copy()
        colors = [(0, 255, 0), (255, 200, 0), (0, 200, 255)]
        for i, (cx, cy, area, cnt) in enumerate(objects[:10]):
            color = colors[i % len(colors)]
            cv2.drawContours(out, [cnt], -1, color, 2)
            wx, wy = pixel_to_world(cx, cy)
            label = f"Obj{i} ({wx:.3f},{wy:.3f})m"
            cv2.putText(out, label, (cx - 40, cy - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            cv2.circle(out, (cx, cy), 4, color, -1)
        return out


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


def mode_single():
    cap = open_camera()
    detector = BackgroundDetector()

    print("1. Clear the desk — press Enter to capture background...")
    input()

    frame = read_frame(cap)
    if frame is None:
        print("Camera error")
        return
    detector.capture_background(frame)
    print("Background saved!\n")

    print("2. Place an object on the desk — press Enter to detect...")
    input()

    frame = read_frame(cap)
    objects = detector.detect(frame)

    if not objects:
        print("No objects detected. Try a larger/different-colored object.")
    else:
        print(f"Found {len(objects)} object(s):")
        for i, (cx, cy, area, _) in enumerate(objects[:5]):
            wx, wy = pixel_to_world(cx, cy)
            print(f"  Object {i}: pixel=({cx},{cy}) → base=({wx:.4f},{wy:.4f})m  area={area:.0f}px²")

    cap.release()


def mode_live():
    from flask import Flask, Response, render_template_string
    import threading as th

    app = Flask(__name__)
    detector = BackgroundDetector()
    display_frame = [None]
    lock = th.Lock()
    bg_mode = [True]  # start in background capture mode

    def capture_loop():
        cap = open_camera()
        frame_count = 0
        while True:
            frame = read_frame(cap)
            if frame is None:
                time.sleep(0.01)
                continue

            frame_count += 1

            if bg_mode[0]:
                # Background capture mode
                if frame_count > 10:
                    detector.capture_background(frame)
                    bg_mode[0] = False
                    print("Auto-captured background")
                with lock:
                    disp = cv2.resize(frame, (640, 640))
                    cv2.putText(disp, "Capturing background... keep desk clear",
                                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
                    display_frame[0] = disp
            else:
                objects = detector.detect(frame)
                out = detector.draw(frame, objects)
                disp = cv2.resize(out, (640, 640))
                cv2.putText(disp, f"Objects: {len(objects)}  |  Press R to reset background",
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
                with lock:
                    display_frame[0] = disp

            time.sleep(0.05)

    HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Background Detection</title>
<style>
body{margin:0;background:#111;display:flex;justify-content:center;align-items:center;
     min-height:100vh;font-family:Segoe UI,sans-serif}
h2{color:#4f9}img{max-width:95vw;max-height:90vh;border:2px solid #333;border-radius:8px}
</style></head>
<body><div style="text-align:center">
<h2>Background Subtraction — Markerless Detection</h2>
<img src="/video_feed"></div></body></html>"""

    @app.route('/')
    def index():
        return render_template_string(HTML)

    @app.route('/reset')
    def reset():
        bg_mode[0] = True
        return "Resetting background..."

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

    th.Thread(target=capture_loop, daemon=True).start()
    time.sleep(2)
    print("\nOpen: http://192.168.58.68:8083")
    app.run(host='0.0.0.0', port=8083, debug=False, threaded=True)


if __name__ == '__main__':
    if '--live' in sys.argv:
        mode_live()
    else:
        mode_single()
