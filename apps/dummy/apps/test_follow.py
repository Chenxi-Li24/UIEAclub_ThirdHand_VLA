#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.director import DummyDirector
from dummy.touch_r1_adapter import TouchR1Adapter


async def main():
    cfg = load_config()
    cfg["timing"]["sleep_after_s"] = 9999
    await DummyDirector(TouchR1Adapter(cfg), cfg).run()


asyncio.run(main())
