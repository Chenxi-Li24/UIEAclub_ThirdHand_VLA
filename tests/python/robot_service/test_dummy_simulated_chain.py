"""Exercise Dummy -> adapter -> real Node service -> simulated Python bridge."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/dummy/src"))

from dummy.config import load_config
from dummy.person_follow.runtime import PersonFollowRuntime
from dummy.robot_ws_client import RobotWebSocketClient
from dummy.touch_r1_adapter import TouchR1Adapter
from dummy.tracker import Target


def test_dummy_follow_keyword_exit_keeps_robot_service_connected(tmp_path):
    node = os.environ.get("THIRDHAND_TEST_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node runtime unavailable")
    ready = tmp_path / "port.json"
    script = """
const fs = require('node:fs');
const { createRobotService } = require('./services/robot/src/server');
const service = createRobotService({ host: '127.0.0.1', port: 0,
  readyFile: process.env.TEST_READY_FILE,
  robot: { python: process.env.TEST_PYTHON, simulate: true, dryRun: false,
    requireCanRx: false, initSettleSec: 0, initSampleCount: 2,
    pollIntervalMs: 20, minMoveTimeSec: 0.05, maxMoveTimeSec: 30 } });
service.start().then(address => {
  fs.writeFileSync(process.env.TEST_PORT_FILE, JSON.stringify(address));
  process.stdin.once('data', () => service.close().then(() => process.exit(0)));
}).catch(error => { console.error(error); process.exit(1); });
"""
    process = subprocess.Popen([node, "-e", script], cwd=ROOT, stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               env={**os.environ, "TEST_PYTHON": sys.executable,
                                    "TEST_PORT_FILE": str(ready),
                                    "TEST_READY_FILE": str(tmp_path / "robot.ready")})
    try:
        deadline = time.monotonic() + 10
        while not ready.is_file() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.is_file(), "simulated Robot Service failed to start"
        port = json.loads(ready.read_text())["port"]
        async def scenario():
            config = load_config()
            config["workspace_guard"]["enabled"] = False  # geometry covered by separate tests
            config["robot"].update(ws_url=f"ws://127.0.0.1:{port}/ws",
                                   health_url=f"http://127.0.0.1:{port}/health",
                                   follow_wait_complete=True)
            adapter = TouchR1Adapter(config)
            await adapter.connect()
            joints = list((await adapter.get_state()).joints_deg)
            runtime = PersonFollowRuntime(adapter, config=config, guard=adapter.workspace_guard, joints=joints)
            observer = RobotWebSocketClient(config["robot"]["ws_url"])
            try:
                # Fill the old event log before issuing a real simulated command.
                for i in range(250):
                    adapter.client._receive({"type": "log", "sequence": i})
                runtime.publish(Target(True, 520, 100, 640, 480, 0.9, "person_lock", time.time()))
                assert await runtime.step()
                assert adapter.follow_active
                await asyncio.sleep(.2)
                after = list((await adapter.get_state()).joints_deg)
                assert after[0] != pytest.approx(joints[0])
                assert all(after[i] == pytest.approx(joints[i]) for i in (1, 2, 4, 5))
                assert any(event.get("type") == "robot_state" and event.get("moving")
                           for event in adapter.client.events)
                assert runtime.queue_keyword("head_tilt")
                keyword_events = []
                adapter.client.listeners.append(keyword_events.append)
                assert await runtime.step()
                assert any(event.get("type") == "robot_state" and event.get("moving")
                           for event in keyword_events)
                assert any(event.get("status") == "complete" for event in adapter.client.events)
                runtime.request_stop()
                await runtime.run()
                assert runtime.mode == "STOPPED"
                state = await observer.refresh_state()
                assert state.connected and state.state_ready and not state.moving
                # Another webpage-like client still controls the shared service.
                reply = await observer.command_wait("gripper", position=0.25, timeout=3)
                assert reply["status"] == "complete"
            finally:
                await adapter.close()
                await observer.close()
        asyncio.run(scenario())
    finally:
        if process.poll() is None:
            process.stdin.write(b"stop\n")
            process.stdin.flush()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
