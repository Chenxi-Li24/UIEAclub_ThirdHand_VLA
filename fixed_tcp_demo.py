#!/usr/bin/env python3
import sys
from pathlib import Path


DEMO_ROOT = Path(__file__).resolve().parent / "fixed_tcp_demo"
if str(DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_ROOT))

from demo import main


if __name__ == "__main__":
    raise SystemExit(main())
