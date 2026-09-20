#!/usr/bin/env python3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.tracker import HumanTracker


tracker = HumanTracker(load_config())
try:
    for _ in range(100):
        print(tracker.read())
        time.sleep(0.1)
finally:
    tracker.close()
