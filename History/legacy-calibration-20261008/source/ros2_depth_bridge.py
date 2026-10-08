"""
ROS2 depth bridge — subscribes to RGB+Depth topics, serves latest frame via HTTP.
Runs with system Python 3.8 (rclpy).
Usage:
  source /opt/ros/galactic/setup.bash
  /usr/bin/python3 ros2_depth_bridge.py
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CameraInfo
from cv_bridge import CvBridge
import numpy as np
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

bridge = CvBridge()
SN = "SN250801DR48FB26001402"

# Shared state
latest = {
    "rgb": None,       # (1280, 1280, 3) BGR
    "depth": None,     # (480, 640) float32 meters
    "rgb_ts": 0,
    "depth_ts": 0,
    "rgb_K": None,     # 3x3 camera matrix
    "depth_K": None,
}
lock = threading.Lock()


class XVSubscriber(Node):
    def __init__(self):
        super().__init__('xv_depth_bridge')

        # RGB
        self.create_subscription(
            Image, f'/xv_sdk/{SN}/rgb/image', self.rgb_cb, 10)
        self.create_subscription(
            CameraInfo, f'/xv_sdk/{SN}/rgb/camera_info', self.rgb_info_cb, 10)

        # Depth (rectified)
        self.create_subscription(
            Image, f'/xv_sdk/{SN}/tof/depth/image_rect_raw', self.depth_cb, 10)
        self.create_subscription(
            CameraInfo, f'/xv_sdk/{SN}/tof/depth/camera_info', self.depth_info_cb, 10)

        self.get_logger().info("Subscribed to RGB + Depth topics")

    def rgb_cb(self, msg):
        try:
            img = bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            with lock:
                latest["rgb"] = img
                latest["rgb_ts"] = time.time()
        except Exception as e:
            self.get_logger().error(f"RGB: {e}")

    def rgb_info_cb(self, msg):
        K = np.array(msg.k).reshape(3, 3)
        with lock:
            latest["rgb_K"] = K

    def depth_cb(self, msg):
        try:
            # 16UC1 in mm → float32 in meters
            depth_raw = bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
            depth_m = depth_raw.astype(np.float32) / 1000.0
            with lock:
                latest["depth"] = depth_m
                latest["depth_ts"] = time.time()
        except Exception as e:
            self.get_logger().error(f"Depth: {e}")

    def depth_info_cb(self, msg):
        K = np.array(msg.k).reshape(3, 3)
        with lock:
            latest["depth_K"] = K


class APIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/depth':
            with lock:
                d = latest["depth"]
                if d is None:
                    self.send_error(404)
                    return
                # Return depth at center + full array stats
                cy, cx = d.shape[0] // 2, d.shape[1] // 2
                center_depth = float(d[cy, cx])
                valid = d[d > 0]
                stats = {
                    "center_depth_m": round(center_depth, 4),
                    "valid_pixels": int(len(valid)),
                    "min_m": round(float(valid.min()), 3) if len(valid) > 0 else 0,
                    "max_m": round(float(valid.max()), 3) if len(valid) > 0 else 0,
                    "mean_m": round(float(valid.mean()), 3) if len(valid) > 0 else 0,
                    "shape": list(d.shape),
                }
                self.send_json(stats)
        elif self.path == '/depth_at':
            # Query depth at specific pixel: /depth_at?u=640&v=640
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            u = int(qs.get('u', [640])[0])
            v = int(qs.get('v', [640])[0])
            with lock:
                d = latest["depth"]
                if d is None:
                    self.send_error(404)
                    return
                # Map from RGB pixel (1280x1280) to depth pixel (480x640)
                # Simple scaling approximation
                du = int(u * d.shape[1] / 1280)
                dv = int(v * d.shape[0] / 960)  # approximate
                du = max(0, min(d.shape[1]-1, du))
                dv = max(0, min(d.shape[0]-1, dv))
                dz = float(d[dv, du])
                self.send_json({"u": u, "v": v, "depth_m": round(dz, 4)})
        elif self.path == '/status':
            with lock:
                self.send_json({
                    "rgb_ok": latest["rgb"] is not None,
                    "depth_ok": latest["depth"] is not None,
                    "rgb_age": round(time.time() - latest["rgb_ts"], 2),
                    "depth_age": round(time.time() - latest["depth_ts"], 2),
                })
        else:
            self.send_json({"endpoints": ["/depth", "/depth_at?u=640&v=640", "/status"]})

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # Suppress logs


def main():
    rclpy.init()
    node = XVSubscriber()

    # ROS2 spin in background thread
    def ros_spin():
        rclpy.spin(node)

    t = threading.Thread(target=ros_spin, daemon=True)
    t.start()

    # HTTP API
    port = 8085
    server = HTTPServer(('0.0.0.0', port), APIHandler)
    print(f"Depth API: http://0.0.0.0:{port}")
    print("Endpoints: /depth /depth_at?u=640&v=640 /status")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
