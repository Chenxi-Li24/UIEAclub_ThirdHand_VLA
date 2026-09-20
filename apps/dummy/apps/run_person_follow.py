#!/usr/bin/env python3
"""Run the real-hardware person-follow loop with safe demo defaults.

Use this entrypoint with the vision-python runtime because that environment
has the OpenCV cascade classifiers used by VisionServiceTracker.
"""

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.director import DummyDirector
from dummy.motion_gate import require_motion_enable
from dummy.single_instance import SingleInstanceLock
from dummy.touch_r1_adapter import TouchR1Adapter


def zero_gesture():
    return {"keyframes": [{"t": 0.0, "offset_deg": [0, 0, 0, 0, 0, 0]}]}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run Dummy person-follow on the real robot")
    parser.add_argument(
        "--enable-motion",
        action="store_true",
        help="explicitly allow this process to send real robot motion commands",
    )
    return parser.parse_args(argv)


async def main():
    cfg = load_config()
    print("[dummy] REAL ROBOT FOLLOW MODE: vision target will command J1/J4/J6", flush=True)
    print("[dummy] Keep an emergency stop / power cut reachable. Ctrl+C stops this demo.", flush=True)

    # Do not jump to a preset before a follow demo. The operator can send Home
    # explicitly after clearing the workspace.
    cfg.setdefault("robot", {})["go_home_on_start"] = False
    cfg.setdefault("robot", {})["go_home_on_lost"] = False
    cfg.setdefault("timing", {})["sleep_after_s"] = 9999

    # The follow loop itself is the test subject here. Keep startup/recovery
    # gestures disabled so near-limit arm poses do not fail before vision starts.
    for name in ("wake_up", "nod", "perk_up", "droop", "sleep"):
        cfg.setdefault("gestures", {})[name] = zero_gesture()

    await DummyDirector(TouchR1Adapter(cfg), cfg).run()


def run(argv=None):
    args = parse_args(argv)
    try:
        # Check operator intent before opening the process lock, robot socket,
        # camera, or any other runtime resource.
        require_motion_enable(args.enable_motion)
        with SingleInstanceLock("/tmp/thirdhand-dummy-person-follow.lock"):
            asyncio.run(main())
    except KeyboardInterrupt:
        return 130
    except RuntimeError as exc:
        print(f"[dummy] {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
