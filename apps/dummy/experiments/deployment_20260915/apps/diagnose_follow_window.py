#!/usr/bin/env python3
"""Human-readable diagnostics window for ThirdHand follow."""

from __future__ import annotations

import argparse
import os
import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.config import load_config
from dummy_legacy.dume_touch_r1_follow import DumeTouchR1FollowController
from dummy_legacy.follow3d.diagnostics import build_diagnostics
from dummy_legacy.tracker import HumanTracker
from dummy_legacy.vision_service_tracker import VisionServiceTracker
from visualize_head_body_window import LiveRobotReader


def build_tracker(config):
    if config.get("vision_service", {}).get("enabled", True):
        return VisionServiceTracker(config), "vision_service"
    return HumanTracker(config), "opencv_v4l"


def _style(level):
    if level == "ok":
        return {"frame": "#ffffff", "border": "#bbf7d0", "badge": "#ffffff", "text": "[OK]", "badge_fg": "#166534", "detail": "#166534"}
    if level == "warn":
        return {"frame": "#fffbeb", "border": "#fde68a", "badge": "#fffbeb", "text": "[CHECK]", "badge_fg": "#92400e", "detail": "#92400e"}
    if level == "bad":
        return {"frame": "#fef2f2", "border": "#fecaca", "badge": "#fef2f2", "text": "[ISSUE]", "badge_fg": "#991b1b", "detail": "#991b1b"}
    return {"frame": "#eff6ff", "border": "#bfdbfe", "badge": "#eff6ff", "text": "[NEXT]", "badge_fg": "#1e3a8a", "detail": "#1e3a8a"}


class App:
    def __init__(self, root, tracker, controller, robot, args, joints):
        self.root = root
        self.tracker = tracker
        self.controller = controller
        self.robot = robot
        self.args = args
        self.joints = list(joints)
        self.labels = []
        self.root.configure(bg="#f3f4f6")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.title_font = ("TkDefaultFont", 17, "bold")
        self.name_font = ("TkDefaultFont", 12, "bold")
        self.detail_font = ("TkDefaultFont", 11)
        self.badge_font = ("TkDefaultFont", 10, "bold")
        title = tk.Label(root, text="ThirdHand Follow Diagnostics", font=self.title_font, anchor="w", bg="#f3f4f6", fg="#111827")
        title.pack(fill="x", padx=16, pady=(14, 2))
        subtitle = tk.Label(root, text="Read top to bottom. Yellow means check; red means the likely problem.", font=self.detail_font, anchor="w", bg="#f3f4f6", fg="#6b7280")
        subtitle.pack(fill="x", padx=16, pady=(0, 8))
        for _ in range(9):
            frame = tk.Frame(root, bg="#ffffff", padx=12, pady=8, highlightthickness=1, highlightbackground="#e5e7eb")
            frame.pack(fill="x", padx=16, pady=4)
            badge = tk.Label(frame, text="", width=6, anchor="w", fg="#374151", bg="#ffffff", font=self.badge_font)
            badge.pack(side="left", padx=(0, 10))
            name = tk.Label(frame, text="", width=10, anchor="w", fg="#111827", bg="#ffffff", font=self.name_font)
            name.pack(side="left")
            detail = tk.Label(frame, text="", anchor="w", fg="#374151", bg="#ffffff", font=self.detail_font)
            detail.pack(side="left", fill="x", expand=True)
            self.labels.append((frame, badge, name, detail))
        self.tick()

    def tick(self):
        target, _frame, error = self.tracker.read_frame() if self.args.tracker_mode == "vision_service" else (self.tracker.read(), None, None)
        debug = dict(getattr(self.tracker, "last_debug", {}) or {})
        snapshot = self.robot.snapshot if self.robot is not None else None
        if snapshot and snapshot.joints_deg and len(snapshot.joints_deg) == 6:
            self.joints = list(snapshot.joints_deg)
        command = self.controller.target_for(self.joints, target, debug=debug)
        if command.debug:
            debug.update(command.debug)
        rows = build_diagnostics(target=target, command=command, debug=debug, error=error, robot_snapshot=snapshot)
        for (frame, badge, name, detail), row in zip(self.labels, rows):
            style = _style(row["level"])
            frame.configure(bg=style["frame"], highlightbackground=style["border"])
            badge.configure(bg=style["badge"], fg=style["badge_fg"], text=style["text"])
            name.configure(bg=style["frame"], text=row["name"])
            detail.configure(bg=style["frame"], text=row["detail"], fg=style["detail"])
        self.root.after(max(100, int(1000 / max(1.0, self.args.hz))), self.tick)

    def close(self):
        self.tracker.close()
        if self.robot is not None:
            self.robot.close()
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Show readable follow diagnostics")
    parser.add_argument("--display", default=os.environ.get("DISPLAY") or ":0")
    parser.add_argument("--hz", type=float, default=4.0)
    parser.add_argument("--width", type=int, default=920)
    parser.add_argument("--height", type=int, default=500)
    parser.add_argument("--robot-ws", default="ws://127.0.0.1:3000/ws")
    parser.add_argument("--robot-health", default="http://127.0.0.1:3000/health")
    parser.add_argument("--live-robot", action="store_true")
    args = parser.parse_args(argv)
    os.environ.setdefault("DISPLAY", args.display)
    config = load_config()
    tracker, mode = build_tracker(config)
    args.tracker_mode = mode
    tracker.open()
    joints = config.get("robot", {}).get("home_joints_deg", [0, 0, 0, 0, 0, 0])
    controller = DumeTouchR1FollowController(config)
    controller.reset(joints)
    robot = None
    if args.live_robot:
        robot = LiveRobotReader(args.robot_ws, args.robot_health)
        robot.start()
    root = tk.Tk()
    root.title("ThirdHand Follow Diagnostics")
    root.geometry(f"{args.width}x{args.height}")
    App(root, tracker, controller, robot, args, joints)
    root.mainloop()


if __name__ == "__main__":
    main()
