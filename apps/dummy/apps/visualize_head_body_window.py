#!/usr/bin/env python3
"""Ubuntu desktop visualizer for the head-body follow algorithm."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.dume_touch_r1_follow import DumeTouchR1FollowController
from dummy.head_body_visualizer import render_head_body_overlay
from dummy.robot_ws_client import RobotWebSocketClient
from dummy.tracker import HumanTracker, Target
from dummy.vision_service_tracker import VisionServiceTracker


def parse_joints(value):
    joints = [float(part.strip()) for part in str(value).split(",")]
    if len(joints) != 6:
        raise argparse.ArgumentTypeError("--joints must contain six comma-separated numbers")
    return joints


def build_tracker(config):
    if config.get("vision_service", {}).get("enabled", True):
        return VisionServiceTracker(config), "vision_service"
    return HumanTracker(config), "opencv_v4l"


class App:
    def __init__(self, root, tracker, controller, robot, args, initial_joints):
        self.root = root
        self.tracker = tracker
        self.controller = controller
        self.robot = robot
        self.args = args
        self.joints = list(initial_joints)
        self.label = tk.Label(root, bg="black")
        self.label.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="starting")
        tk.Label(root, textvariable=self.status, anchor="w").pack(fill="x")
        self.photo = None
        self.running = True
        self.last_frame = time.time()
        self.fps = 0.0
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    def tick(self):
        if not self.running:
            return
        target, frame, error, debug = self._read_target_and_frame()
        if frame is None:
            frame = self._blank_frame(target, error)

        self._refresh_live_joints()
        follow_command = self.controller.target_for(self.joints, target, debug=debug)
        command = follow_command.joints_deg if hasattr(follow_command, "joints_deg") else follow_command
        if hasattr(follow_command, "debug") and follow_command.debug:
            debug.update(follow_command.debug)
        if self.robot is None and target.found and not str(target.kind).endswith("_hold"):
            # Dry-run preview advances its local state so operators can see the
            # expected head-first/body-follow behavior before arming hardware.
            self.joints = list(command)

        now = time.time()
        dt = max(1e-6, now - self.last_frame)
        self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt) if self.fps else 1.0 / dt
        self.last_frame = now
        overlay = render_head_body_overlay(
            frame,
            target,
            command,
            self.joints,
            debug=debug,
            error=error,
            enabled=self.args.enable_motion_preview,
            gateway_url=self.args.gateway_url,
        )
        cv2.putText(
            overlay,
            f"fps={self.fps:.1f}  tracker={self.args.tracker_mode}",
            (overlay.shape[1] - 280, overlay.shape[0] - 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        image.thumbnail((self.args.width, self.args.height))
        self.photo = ImageTk.PhotoImage(image)
        self.label.configure(image=self.photo)
        self.status.set(
            f"{debug.get('control_source', '-')} | "
            f"{debug.get('estimated_depth_source', '-')}:{float(debug.get('estimated_depth_m', 0.0) or 0.0):.2f}m | "
            f"{debug.get('distance_state', '-')} | "
            f"{target.kind if target.found else 'none'}"
        )
        self.root.after(max(10, int(1000 / max(1.0, self.args.hz))), self.tick)

    def _read_target_and_frame(self):
        if self.args.tracker_mode == "vision_service":
            target, frame, error = self.tracker.read_frame()
            return target, frame, error, dict(getattr(self.tracker, "last_debug", {}) or {})
        target = self.tracker.read()
        debug = getattr(self.tracker, "last_debug", {})
        frame = debug.get("gray")
        if frame is not None:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        return target, frame, None, dict(debug or {})

    def _blank_frame(self, target, error):
        frame = np.zeros((self.args.frame_h, self.args.frame_w, 3), dtype=np.uint8)
        message = error or f"waiting for {self.args.tracker_mode}"
        cv2.putText(frame, message, (24, self.args.frame_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 180, 255), 2)
        if target is None:
            return frame
        return frame

    def close(self):
        self.running = False
        self.tracker.close()
        if self.robot is not None:
            self.robot.close()
        self.root.destroy()

    def _refresh_live_joints(self):
        if self.robot is None:
            return
        snapshot = self.robot.snapshot
        if snapshot.joints_deg and len(snapshot.joints_deg) == 6:
            self.joints = list(snapshot.joints_deg)


class LiveRobotReader:
    def __init__(self, ws_url, health_url):
        self.client = RobotWebSocketClient(ws_url, health_url)
        self.snapshot = self.client.snapshot
        self.stop = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop = True

    def _run(self):
        asyncio.run(self._main())

    async def _main(self):
        await self.client.open()
        while not self.stop:
            await self.client.command("status")
            self.snapshot = self.client.snapshot
            await asyncio.sleep(0.12)
        await self.client.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Show head-body vision/control overlay on Ubuntu desktop")
    parser.add_argument("--display", default=os.environ.get("DISPLAY") or ":0")
    parser.add_argument("--joints", type=parse_joints, default=None)
    parser.add_argument("--hz", type=float, default=12.0)
    parser.add_argument("--width", type=int, default=1180)
    parser.add_argument("--height", type=int, default=880)
    parser.add_argument("--gateway-url", default="ws://127.0.0.1:31023/ws")
    parser.add_argument("--robot-ws", default="ws://127.0.0.1:3000/ws")
    parser.add_argument("--robot-health", default="http://127.0.0.1:3000/health")
    parser.add_argument("--live-robot", action="store_true", help="read live robot joints for the overlay")
    parser.add_argument("--enable-motion-preview", action="store_true", help="only changes overlay label; this visualizer never sends robot commands")
    args = parser.parse_args(argv)
    os.environ.setdefault("DISPLAY", args.display)

    config = load_config()
    tracker, mode = build_tracker(config)
    args.tracker_mode = mode
    args.frame_w = int(config.get("vision", {}).get("frame_w", 640))
    args.frame_h = int(config.get("vision", {}).get("frame_h", 480))
    joints = args.joints or config.get("robot", {}).get(
        "home_joints_deg",
        [-0.163927, -2.611904, -4, 33.058620, 0.338783, 0.185784],
    )
    controller = DumeTouchR1FollowController(config)
    controller.reset(joints)
    robot = None
    if args.live_robot:
        robot = LiveRobotReader(args.robot_ws, args.robot_health)
        robot.start()
    opened = tracker.open() if hasattr(tracker, "open") else True
    if not opened:
        print(f"[dummy] visualizer opened without initial {mode} frame; window will keep retrying", flush=True)

    root = tk.Tk()
    root.title("ThirdHand Head-Body Vision Debug")
    root.geometry(f"{args.width}x{args.height}")
    App(root, tracker, controller, robot, args, joints)
    root.mainloop()


if __name__ == "__main__":
    main()
