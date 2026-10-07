#!/usr/bin/env python3
"""Small supervised axis calibration helper for Touch R1 as a DUM-E camera head."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.motion_gate import require_motion_enable
from dummy.touch_r1_adapter import TouchR1Adapter


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Nudge one Touch R1 joint for camera-gimbal calibration")
    parser.add_argument("--enable-motion", action="store_true")
    parser.add_argument("--joint", type=int, required=True, choices=range(1, 7), help="1-based joint index")
    parser.add_argument("--delta-deg", type=float, default=2.0)
    parser.add_argument("--robot-ws", default="ws://127.0.0.1:31023/ws")
    parser.add_argument("--robot-health", default="http://127.0.0.1:3000/health")
    parser.add_argument("--return-zero", action="store_true", help="return to zero preset after the nudge")
    return parser.parse_args(argv)


async def main(args):
    cfg = load_config()
    cfg.setdefault("robot", {})["ws_url"] = args.robot_ws
    cfg["robot"]["health_url"] = args.robot_health
    cfg["robot"]["home_joints_deg"] = None
    cfg["robot"]["home_preset_name"] = "zero"
    cfg["robot"]["max_relative_move_deg"] = max(abs(args.delta_deg), 0.75)
    cfg["robot"]["follow_speed_percent"] = 0.05
    cfg["robot"]["servo_min_time_sec"] = 0.50
    adapter = TouchR1Adapter(cfg)
    await adapter.connect()
    try:
        state = await adapter.get_state()
        joints = list(state.joints_deg)
        if len(joints) != 6:
            raise RuntimeError("robot state does not contain six joints")
        joints[args.joint - 1] += float(args.delta_deg)
        print(f"[calibrate] nudging J{args.joint} by {args.delta_deg:.2f} deg", flush=True)
        await adapter.send_joint_target(joints, time_sec=0.8)
        await adapter.wait_idle(timeout=10.0)
        print("[calibrate] observe visualizer: target moved left/right/up/down/roll?", flush=True)
        if args.return_zero:
            await adapter.go_home()
    finally:
        await adapter.close()


def run(argv=None):
    args = parse_args(argv)
    if args.enable_motion:
        require_motion_enable(True)
    else:
        print("[calibrate] add --enable-motion to move hardware", file=sys.stderr, flush=True)
        return 2
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
