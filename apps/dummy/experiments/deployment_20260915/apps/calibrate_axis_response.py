#!/usr/bin/env python3
"""Measure how each Touch R1 joint moves the locked person in the image.

This is a live hardware commissioning helper. It sends small joint offsets
through the existing Robot Service / 31023 gateway path, then measures the
change in the local person-lock target. It does not talk to CAN directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.config import load_config
from dummy_legacy.motion_gate import require_motion_enable
from dummy_legacy.touch_r1_adapter import TouchR1Adapter
from dummy_legacy.vision_service_tracker import VisionServiceTracker


def parse_joints(value):
    joints = []
    for part in str(value).split(","):
        part = part.strip().lower().replace("j", "")
        if not part:
            continue
        joints.append(int(part) - 1)
    if not joints or any(item < 0 or item > 5 for item in joints):
        raise argparse.ArgumentTypeError("--joints must be like 1,4,5")
    return joints


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Live image-axis response calibration")
    parser.add_argument("--enable-motion", action="store_true")
    parser.add_argument("--joints", type=parse_joints, default=parse_joints("1,4,5"))
    parser.add_argument("--step-deg", type=float, default=2.0)
    parser.add_argument("--settle-s", type=float, default=0.8)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--sample-s", type=float, default=0.10)
    parser.add_argument("--skip-home", action="store_true")
    parser.add_argument("--robot-ws", default="ws://127.0.0.1:31023/ws")
    parser.add_argument("--robot-health", default="http://127.0.0.1:3000/health")
    parser.add_argument("--output", default="logs/axis-response.json")
    parser.add_argument("--max-step-output-deg", type=float, default=1.2)
    parser.add_argument("--max-excursion-deg", type=float, default=45.0)
    return parser.parse_args(argv)


async def sample_target(tracker, *, samples, sample_s):
    seen = []
    last_error = None
    last_kind = "none"
    for _ in range(max(1, int(samples))):
        target, _frame, _error = tracker.read_frame()
        last_kind = getattr(target, "kind", "none")
        if getattr(target, "found", False):
            ex = float(target.u) - float(target.w) / 2.0
            ey = float(target.v) - float(target.h) / 2.0
            seen.append((ex, ey))
            last_error = (ex, ey)
        await asyncio.sleep(max(0.02, float(sample_s)))
    if not seen:
        raise RuntimeError(f"person target not locked; last_kind={last_kind}")
    return {
        "error_px": [sum(item[0] for item in seen) / len(seen), sum(item[1] for item in seen) / len(seen)],
        "samples": len(seen),
        "last_error_px": list(last_error),
        "kind": last_kind,
    }


async def main(argv=None):
    args = parse_args(argv)
    require_motion_enable(args.enable_motion)
    cfg = load_config()
    robot = cfg.setdefault("robot", {})
    robot["ws_url"] = args.robot_ws
    robot["health_url"] = args.robot_health
    robot["follow_command"] = "move_joint"
    robot["max_relative_move_deg"] = max(0.5, min(3.0, abs(float(args.step_deg)) + 0.5))
    robot["min_command_interval_s"] = 0.15
    robot["servo_min_time_sec"] = 0.60
    robot["home_joints_deg"] = None
    robot["home_preset_name"] = "zero"

    tracker = VisionServiceTracker(cfg)
    adapter = TouchR1Adapter(cfg)
    if not tracker.open():
        raise RuntimeError("vision tracker did not open")
    await adapter.connect()
    try:
        if not args.skip_home:
            print("[axis-cal] returning to zero before calibration", flush=True)
            await adapter.go_home()
        state = await adapter.get_state()
        base = list(state.joints_deg)
        if len(base) != 6:
            raise RuntimeError("robot state did not provide six joints")
        print(f"[axis-cal] base q={[round(v, 3) for v in base]}", flush=True)

        before = await sample_target(tracker, samples=args.samples, sample_s=args.sample_s)
        print(f"[axis-cal] base err={_fmt(before['error_px'])}", flush=True)
        rows = []
        for joint in args.joints:
            for direction in (1.0, -1.0):
                step = direction * abs(float(args.step_deg))
                target = list(base)
                target[joint] += step
                print(f"[axis-cal] J{joint + 1} step {step:+.2f} deg", flush=True)
                await adapter.send_joint_target(target, time_sec=0.8, allow_large=True)
                await wait_motion_settled(adapter, timeout=8.0)
                await asyncio.sleep(max(0.1, float(args.settle_s)))
                after = await sample_target(tracker, samples=args.samples, sample_s=args.sample_s)
                delta = [
                    after["error_px"][0] - before["error_px"][0],
                    after["error_px"][1] - before["error_px"][1],
                ]
                row = {
                    "joint": joint + 1,
                    "step_deg": step,
                    "before_error_px": before["error_px"],
                    "after_error_px": after["error_px"],
                    "delta_error_px": delta,
                    "px_per_deg": [delta[0] / step, delta[1] / step],
                }
                rows.append(row)
                print(
                    f"[axis-cal] J{joint + 1} {step:+.2f}: "
                    f"delta={_fmt(delta)} px_per_deg={_fmt(row['px_per_deg'])}",
                    flush=True,
                )
                await adapter.send_joint_target(base, time_sec=0.8, allow_large=True)
                await wait_motion_settled(adapter, timeout=8.0)
                await asyncio.sleep(max(0.1, float(args.settle_s)))
                before = await sample_target(tracker, samples=args.samples, sample_s=args.sample_s)

        result = {
            "created_at": time.time(),
            "step_deg": abs(float(args.step_deg)),
            "base_joints_deg": base,
            "rows": rows,
            "summary": summarize(rows, max_step_deg=args.max_step_output_deg, max_excursion_deg=args.max_excursion_deg),
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[axis-cal] wrote {output}", flush=True)
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2), flush=True)
    finally:
        tracker.close()
        await adapter.close()


async def wait_motion_settled(adapter, *, timeout):
    try:
        await adapter.wait_idle(timeout=timeout)
        return
    except TimeoutError:
        pass
    state = await adapter.get_state()
    if getattr(state, "moving", False):
        raise TimeoutError("robot did not become idle after calibration move")
    print("[axis-cal] wait_idle timed out, but Robot Service reports idle; continuing", flush=True)


def summarize(rows, *, max_step_deg, max_excursion_deg):
    out = {}
    for joint in sorted({row["joint"] for row in rows}):
        related = [row for row in rows if row["joint"] == joint]
        if not related:
            continue
        avg_x = sum(row["px_per_deg"][0] for row in related) / len(related)
        avg_y = sum(row["px_per_deg"][1] for row in related) / len(related)
        out[f"J{joint}"] = {
            "avg_px_per_deg": [avg_x, avg_y],
            "dominant_axis": "x" if abs(avg_x) >= abs(avg_y) else "y",
            "moves_target": "right/down for positive joint" if (avg_x + avg_y) >= 0 else "left/up for positive joint",
            "image_jacobian_axis": {
                "name": f"J{joint}_calibrated",
                "joint_index": joint - 1,
                "px_per_deg": [avg_x, avg_y],
                "max_step_deg": float(max_step_deg),
                "max_excursion_deg": float(max_excursion_deg),
                "enabled": True,
            },
        }
    return out


def _fmt(values):
    return f"({float(values[0]):+.1f},{float(values[1]):+.1f})"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
