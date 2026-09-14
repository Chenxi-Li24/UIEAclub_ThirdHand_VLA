"""Allow examples to run from an unpacked source release before installation."""

from __future__ import annotations

import sys
from pathlib import Path


def add_checkout_src() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
