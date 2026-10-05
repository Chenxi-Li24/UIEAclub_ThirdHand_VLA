import ast
import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR / "src"))

from dummy.robot_ws_client import RobotSnapshot
from dummy.touch_r1_adapter import TouchR1Adapter


def adapter_with_fake_client(status="complete"):
    adapter = TouchR1Adapter({"workspace_guard": {"enabled": False}})
    client = adapter.client
    client.snapshot = RobotSnapshot(
        connected=True, state_ready=True, state_name="IDLE",
        joints_deg=[0, 0, -10, 0, 0, 0],
    )
    client.refresh_state = AsyncMock(return_value=client.snapshot)
    client.command = AsyncMock()
    client.command_wait = AsyncMock(return_value={"type": "command_status", "status": status})
    return adapter


def test_adapter_defaults_to_direct_robot_service():
    adapter = adapter_with_fake_client()
    assert adapter.client.url == "ws://127.0.0.1:3000/ws"
    assert adapter.client.health_url == "http://127.0.0.1:3000/health"


@pytest.mark.parametrize("filename", [
    "run_head_body_follow.py", "run_follow_stack.py",
    "calibrate_axis_response.py", "calibrate_touch_r1_gimbal.py",
    "visualize_head_body_window.py",
])
def test_entrypoint_robot_default_is_direct_3000(filename):
    tree = ast.parse((APP_DIR / "apps" / filename).read_text(encoding="utf-8"))
    defaults = [
        keyword.value.value
        for call in ast.walk(tree) if isinstance(call, ast.Call)
        if any(isinstance(arg, ast.Constant) and arg.value == "--robot-ws" for arg in call.args)
        for keyword in call.keywords if keyword.arg == "default"
    ]
    assert defaults == ["ws://127.0.0.1:3000/ws"]


def test_production_config_uses_adapter_robot_contract():
    config = yaml.safe_load((APP_DIR / "configs/person_follow_production.yaml").read_text())
    adapter = TouchR1Adapter(config)
    assert adapter.client.url == "ws://127.0.0.1:3000/ws"
    assert adapter.completion_timeout == 45.0
    assert adapter.min_command_interval == 0.10


@pytest.mark.parametrize("target", [
    [163, 0, -10, 0, 0, 0], [0, -13, -10, 0, 0, 0],
    [0, 0, 1, 0, 0, 0], [0, 0, -10, 99, 0, 0],
    [0, 0, -10, 0, 99, 0], [0, 0, -10, 0, 0, 165],
    [float("nan"), 0, -10, 0, 0, 0], [float("inf"), 0, -10, 0, 0, 0],
    [0, 0, -10],
])
def test_invalid_joint_target_is_not_sent(target):
    adapter = adapter_with_fake_client()
    with pytest.raises(ValueError):
        asyncio.run(adapter.send_joint_target(target))
    adapter.client.command_wait.assert_not_awaited()


def test_direct_motion_retains_full_target_and_interval_without_speed_override(monkeypatch):
    adapter = adapter_with_fake_client()
    adapter._last_send = time.monotonic()
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    assert asyncio.run(adapter.send_joint_target([5, 0, -10, 0, 0, 0]))
    sleep.assert_awaited_once()
    args, payload = adapter.client.command_wait.call_args
    assert args == ("move_joint",)
    assert payload["joints_deg"] == [5, 0, -10, 0, 0, 0]
    assert "time_sec" not in payload
    assert payload["timeout"] == 45.0
    assert payload["request_id"].startswith("dummy-follow-")
    assert payload["terminal_only"] is True
    assert payload["source"] == "dummy_follow"


def test_busy_motion_is_not_sent():
    adapter = adapter_with_fake_client()
    adapter.client.snapshot.moving = True
    assert asyncio.run(adapter.send_joint_target([1, 0, -10, 0, 0, 0], skip_if_busy=True)) is False
    adapter.client.command_wait.assert_not_awaited()


def test_workspace_guard_still_rejects_before_sending():
    adapter = adapter_with_fake_client()
    adapter.workspace_guard.check = lambda _: (False, "below_base_plane")
    with pytest.raises(RuntimeError, match="workspace guard rejected"):
        asyncio.run(adapter.send_joint_target([1, 0, -10, 0, 0, 0]))
    adapter.client.command_wait.assert_not_awaited()


@pytest.mark.parametrize("status", ["failed", "rejected", "uncertain"])
def test_failed_command_status_is_not_treated_as_success(status):
    adapter = adapter_with_fake_client(status)
    with pytest.raises(RuntimeError, match=status):
        asyncio.run(adapter.send_joint_target([1, 0, -10, 0, 0, 0]))


def test_timeout_is_not_treated_as_success():
    adapter = adapter_with_fake_client()
    adapter.client.command_wait.return_value = None
    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(adapter.send_joint_target([1, 0, -10, 0, 0, 0]))


@pytest.mark.parametrize("position", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_gripper_position_is_not_sent(position):
    adapter = adapter_with_fake_client()
    with pytest.raises(ValueError):
        asyncio.run(adapter.set_gripper(position))
    adapter.client.command.assert_not_awaited()


class SimulatedRobotSocket:
    """Exercise the real client and adapter without opening any network socket."""

    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.incoming.get()
        if message is None:
            raise StopAsyncIteration
        return json.dumps(message)

    async def send(self, raw):
        message = json.loads(raw)
        self.sent.append(message)
        cmd = message["cmd"]
        if cmd in {"connect", "status"}:
            await self.incoming.put({
                "type": "robot_state", "joints": [0, 0, -10, 0, 0, 0],
                "stateName": "IDLE", "healthy": True,
            })
        elif cmd == "move_joint":
            for request_id, status in [("another-client", "failed"), (message["request_id"], "accepted"), (message["request_id"], "complete")]:
                await self.incoming.put({"type": "command_status", "request_id": request_id, "status": status})

    async def close(self):
        await self.incoming.put(None)


def test_direct_connect_motion_feedback_and_close(monkeypatch):
    async def exercise():
        socket = SimulatedRobotSocket()
        connect = AsyncMock(return_value=socket)
        monkeypatch.setattr("dummy.robot_ws_client.websockets.connect", connect)
        adapter = TouchR1Adapter({"workspace_guard": {"enabled": False}})
        monkeypatch.setattr(adapter.client, "health", lambda: {"robot": {"connected": False}})
        try:
            state = await adapter.connect()
            assert state.connected and state.state_ready
            assert await adapter.send_joint_target([1, 0, -10, 0, 0, 0])
            await adapter.set_gripper(0.8)
            await adapter.software_stop()
        finally:
            await adapter.close()
        connect.assert_awaited_once_with("ws://127.0.0.1:3000/ws", open_timeout=5.0)
        commands = [item["cmd"] for item in socket.sent]
        assert "move_joint" in commands and "gripper" in commands and "software_stop" in commands
        assert "disconnect" not in commands
        move = next(item for item in socket.sent if item["cmd"] == "move_joint")
        assert move["joints_deg"] == [1, 0, -10, 0, 0, 0]
        assert move["request_id"].startswith("dummy-follow-")

    asyncio.run(exercise())


def load_stack():
    spec = importlib.util.spec_from_file_location("dummy_follow_stack_test", APP_DIR / "apps/run_follow_stack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stack_launches_follow_with_direct_endpoint(monkeypatch):
    stack = load_stack()
    args = stack.parse_args(["--robot-ws", "ws://ubuntu:3000/ws", "--robot-health", "http://ubuntu:3000/health"])
    launched = []
    monkeypatch.setattr(stack, "start_background", lambda name, command, *a, **k: launched.append((name, command)) or type("Process", (), {"pid": 1, "wait": lambda self: 0})())
    stack.run_follow(args)
    assert len(launched) == 1
    command = launched[0][1]
    assert command[command.index("--robot-ws") + 1] == "ws://ubuntu:3000/ws"


def test_stack_connect_uses_adapter_and_closes_without_disabling_sdk(monkeypatch):
    stack = load_stack()
    state = RobotSnapshot(connected=True, state_ready=True, joints_deg=[0] * 6)
    adapter = type("Adapter", (), {"connect": AsyncMock(return_value=state), "close": AsyncMock()})()
    configs = []
    monkeypatch.setattr(stack, "TouchR1Adapter", lambda config: configs.append(config) or adapter)
    assert asyncio.run(stack._connect_robot("ws://ubuntu:3000/ws", "http://ubuntu:3000/health")) == [0] * 6
    assert configs[0]["robot"]["ws_url"] == "ws://ubuntu:3000/ws"
    assert configs[0]["robot"]["health_url"] == "http://ubuntu:3000/health"
    adapter.close.assert_awaited_once()


def test_stack_closes_adapter_on_connection_failure(monkeypatch):
    stack = load_stack()
    adapter = type("Adapter", (), {"connect": AsyncMock(side_effect=TimeoutError("no state")), "close": AsyncMock()})()
    monkeypatch.setattr(stack, "TouchR1Adapter", lambda _: adapter)
    with pytest.raises(TimeoutError):
        asyncio.run(stack._connect_robot("ws://127.0.0.1:3000/ws", "http://127.0.0.1:3000/health"))
    adapter.close.assert_awaited_once()


def test_stack_exit_signals_only_its_dummy_child(monkeypatch):
    stack = load_stack()
    args = stack.parse_args(["--enable-motion"])
    calls = []
    class Process:
        pid = 1
        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            if timeout is None:
                raise KeyboardInterrupt
            return 0
        def poll(self):
            return None
        def send_signal(self, signum):
            calls.append(("signal", signum))
    monkeypatch.setattr(stack, "start_background", lambda *_args, **_kwargs: Process())
    with pytest.raises(KeyboardInterrupt):
        stack.run_follow(args)
    assert calls == [("wait", None), ("signal", stack.signal.SIGTERM), ("wait", 60)]
