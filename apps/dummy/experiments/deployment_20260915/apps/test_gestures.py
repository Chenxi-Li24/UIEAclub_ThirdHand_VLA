#!/usr/bin/env python3
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.config import load_config
from dummy_legacy.gestures import GestureLibrary
from dummy_legacy.motion_player import MotionPlayer
from dummy_legacy.touch_r1_adapter import TouchR1Adapter


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("gesture", choices=["idle_breathe", "nod", "head_tilt", "droop", "perk_up", "wiggle", "search", "sleep", "wake_up"])
    args = parser.parse_args()
    cfg = load_config()
    adapter = TouchR1Adapter(cfg)
    await adapter.connect()
    await MotionPlayer(adapter, cfg).play(args.gesture, GestureLibrary(cfg).get(args.gesture))
    await adapter.close()


asyncio.run(main())
