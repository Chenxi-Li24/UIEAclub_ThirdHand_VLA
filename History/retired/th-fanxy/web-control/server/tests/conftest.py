"""Make standalone server modules importable during local test collection."""

from __future__ import annotations

import sys
from pathlib import Path


SERVER_ROOT = Path(__file__).parents[1]
server_root = str(SERVER_ROOT)
if server_root not in sys.path:
    sys.path.insert(0, server_root)
