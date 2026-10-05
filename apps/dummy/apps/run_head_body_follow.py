#!/usr/bin/env python3
"""Unified J1/J4 follow and keyword scheduler. Dry-run unless explicitly enabled."""

from __future__ import annotations

import argparse
import asyncio
import math
import signal
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.motion_gate import require_motion_enable
from dummy.person_follow.runtime import PersonFollowRuntime
from dummy.single_instance import SingleInstanceLock
from dummy.touch_r1_adapter import TouchR1Adapter
from dummy.tracker import HumanTracker
from dummy.vision_service_tracker import VisionServiceTracker
from dummy.wake_word import WakeWordDetector
from dummy.workspace_guard import WorkspaceGuard


def parse_joints(value):
    joints = [float(part.strip()) for part in str(value).split(",")]
    if len(joints) != 6 or not all(math.isfinite(x) for x in joints):
        raise argparse.ArgumentTypeError("--joints requires six finite degree values")
    return joints


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Dummy J1/J4 follow and keyword actions")
    parser.add_argument("--enable-motion", action="store_true")
    parser.add_argument("--joints", type=parse_joints, default=None)
    parser.add_argument("--hz", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--robot-ws", default="ws://127.0.0.1:3000/ws")
    parser.add_argument("--robot-health", default="http://127.0.0.1:3000/health")
    parser.add_argument("--skip-home", action="store_true", help="compatibility flag; no automatic Home is issued")
    parser.add_argument("--no-keywords", action="store_true")
    args = parser.parse_args(argv)
    if not math.isfinite(args.hz) or args.hz <= 0:
        parser.error("--hz must be finite and positive")
    return args


def build_tracker(config):
    if config.get("vision_service", {}).get("enabled", True):
        return VisionServiceTracker(config), "vision_service"
    return HumanTracker(config), "opencv_v4l"


async def run_loop(config, args):
    robot = config.setdefault("robot", {})
    robot.update(ws_url=args.robot_ws, health_url=args.robot_health,
                 follow_wait_complete=True, go_home_on_start=False, go_home_on_lost=False)
    config.setdefault("vision_service", {})["rgbd_enabled"] = False
    guard = WorkspaceGuard(config)
    tracker, tracker_mode = build_tracker(config)
    adapter = TouchR1Adapter(config, workspace_guard=guard) if args.enable_motion else None
    runtime = None
    loop = asyncio.get_running_loop()
    registered = []
    previous_handlers = {}
    try:
        if adapter is not None:
            if guard.enabled and not guard.available:
                raise RuntimeError(f"workspace guard unavailable: {guard.unavailable_reason}")
            await adapter.connect()
            joints = list((await adapter.get_state()).joints_deg)
        else:
            joints = args.joints or [0.0] * 6
        runtime = PersonFollowRuntime(adapter, config=config, guard=guard, joints=joints,
                                     period_s=1.0 / max(0.5, args.hz))
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, runtime.request_stop)
                registered.append(signum)
            except NotImplementedError:
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, lambda _signum, _frame: loop.call_soon_threadsafe(runtime.request_stop))
        print(f"[dummy] unified runtime tracker={tracker_mode} motion={args.enable_motion} "
              "follow=J1/J4 keywords=all-joints idle-breathing=off; Ctrl+C exits Dummy only", flush=True)
        await runtime.run(tracker=tracker, keywords=None if args.no_keywords else WakeWordDetector(config),
                          max_steps=args.max_frames)
    finally:
        for signum in registered:
            loop.remove_signal_handler(signum)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        if runtime is None:
            tracker.close()
            if adapter is not None:
                await adapter.close()


def run(argv=None):
    args = parse_args(argv)
    try:
        if args.enable_motion:
            require_motion_enable(True)
        config = load_config()
        if args.enable_motion:
            with SingleInstanceLock(Path(tempfile.gettempdir()) / "thirdhand-dummy-runtime.lock"):
                asyncio.run(run_loop(config, args))
        else:
            asyncio.run(run_loop(config, args))
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, ValueError, TimeoutError, ConnectionError) as exc:
        print(f"[dummy] {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
