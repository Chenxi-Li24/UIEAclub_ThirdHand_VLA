#!/usr/bin/env python3
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.touch_r1_adapter import TouchR1Adapter


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--joint", type=int, default=5)
    parser.add_argument("--deg", type=float, default=0.5)
    args = parser.parse_args()
    adapter = TouchR1Adapter(load_config())
    state = await adapter.connect()
    base = list(state.joints_deg)
    print("base", base)
    target = list(base)
    target[args.joint - 1] += args.deg
    await adapter.send_joint_target(target)
    await asyncio.sleep(1.0)
    await adapter.send_joint_target(base)
    await asyncio.sleep(1.0)
    print("returned")
    await adapter.close()


asyncio.run(main())
