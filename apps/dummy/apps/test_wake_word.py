#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.wake_word import WakeWordDetector


async def main():
    print("Type ThirdHand and press Enter, or speak if speech service is connected.")
    async for event in WakeWordDetector(load_config()).events():
        print(event)
        return


asyncio.run(main())
