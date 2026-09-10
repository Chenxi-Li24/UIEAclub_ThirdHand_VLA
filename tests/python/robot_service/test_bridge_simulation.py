import json
import os
from pathlib import Path
import selectors
import subprocess
import time


ROOT = Path(__file__).resolve().parents[3]
BRIDGE = ROOT / "services" / "robot" / "src" / "startouch_bridge.py"


def read_until(process, predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    while (remaining := deadline - time.monotonic()) > 0:
        if not selector.select(remaining):
            break
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                raise AssertionError(f"bridge exited: {process.stderr.read()}")
            continue
        message = json.loads(line)
        if predicate(message):
            return message
    raise AssertionError("bridge event timeout")


def test_bridge_simulation_requires_explicit_connect():
    env = {
        **os.environ,
        "STARTOUCH_SIMULATE": "1",
        "STARTOUCH_REQUIRE_CAN_RX": "0",
        "STARTOUCH_POLL_INTERVAL_MS": "20",
        "STARTOUCH_JOINT_LOG_INTERVAL_MS": "1000",
    }
    process = subprocess.Popen(
        ["python3", "-u", str(BRIDGE)],
        cwd=BRIDGE.parent,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready = read_until(process, lambda item: item["type"] == "bridge_ready")
        assert ready["simulated"] is True

        process.stdin.write(json.dumps({"cmd": "get_state"}) + "\n")
        process.stdin.flush()
        error = read_until(process, lambda item: item["type"] == "error")
        assert "not connected" in error["message"]

        process.stdin.write(json.dumps({"cmd": "connect"}) + "\n")
        process.stdin.flush()
        connected = read_until(
            process,
            lambda item: item["type"] == "connection" and item["connected"],
        )
        assert connected["simulated"] is True
    finally:
        if process.poll() is None:
            process.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
            process.stdin.flush()
        process.wait(timeout=4)
