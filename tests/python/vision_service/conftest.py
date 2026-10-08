"""Resolve migrated bridge modules without importing any hardware SDK."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/vision/python"))


@pytest.fixture(autouse=True)
def project_paths(monkeypatch):
    monkeypatch.setenv("THIRDHAND_LIVE_ROOT", str(ROOT))
