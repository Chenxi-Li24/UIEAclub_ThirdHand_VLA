#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.config import load_config
from dummy_legacy.director import DummyDirector
from dummy_legacy.touch_r1_adapter import TouchR1Adapter


async def main():
    cfg = load_config()
    await DummyDirector(TouchR1Adapter(cfg), cfg).run()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
