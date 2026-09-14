#!/usr/bin/env python3
"""Standalone Lumos MJPEG streamer. No pyrealsense2, no arm, just pure OpenCV.

Writes MJPEG stream to stdout. Called by proxy.js as a child process.
"""
import sys, time, signal
import cv2
import numpy as np

running = True

def _handle_signal(signum, frame):
    global running
    running = False

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

# Open Lumos camera
cap = None
for idx in [1, 0]:
    c = cv2.VideoCapture(idx)
    if c.isOpened():
        cap = c
        break
    c.release()

if cap is None:
    sys.stderr.write("LUMOS: camera not found\n")
    sys.stderr.flush()
    sys.exit(1)

cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YU12'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
sys.stderr.write("LUMOS: streaming started\n")
sys.stderr.flush()

while running:
    try:
        ret, raw = cap.read()
        if not ret:
            time.sleep(0.01)
            continue
        frame = cv2.cvtColor(raw, cv2.COLOR_YUV2BGR_I420)
        frame = cv2.resize(frame, (320, 320))
        _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
        sys.stdout.buffer.write(
            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n"
        )
        sys.stdout.buffer.flush()
    except Exception:
        time.sleep(0.05)

cap.release()
sys.stderr.write("LUMOS: stopped\n")
