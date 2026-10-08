"""Run the saved bridge fixture as an isolated process without a CAN/SDK owner."""
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def test_existing_arm_fixture():
    result = subprocess.run(
        [sys.executable, str(ROOT / "services/robot/src/test_fixed_tcp_bridge.py")],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_demo_source_uses_relocated_application():
    source = (ROOT / "services/robot/src/startouch_bridge.py").read_text()
    assert '"apps" / "fixed_tcp_demo"' in source
