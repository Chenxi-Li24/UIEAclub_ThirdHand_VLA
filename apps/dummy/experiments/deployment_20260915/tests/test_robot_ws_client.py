import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.robot_ws_client import RobotWebSocketClient


class FakeClient(RobotWebSocketClient):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def command(self, cmd, **kwargs):
        self.sent.append((cmd, kwargs))


def run(coro):
    return asyncio.run(coro)


async def _ignores_unrelated_motion_state_without_request_id():
    client = FakeClient()
    client.events.append({"type": "motion_state", "stateName": "MOVING"})

    result = await client.command_wait("move_joint", request_id="req-1", timeout=0.01)

    assert result is None


async def _returns_matching_command_status():
    client = FakeClient()

    async def inject():
        await asyncio.sleep(0)
        client.events.append({"type": "command_status", "request_id": "req-1", "status": "complete"})
        async with client._event_condition:
            client._event_condition.notify_all()

    task = asyncio.create_task(inject())
    result = await client.command_wait("move_joint", request_id="req-1", timeout=0.5)
    await task

    assert result["type"] == "command_status"
    assert result["request_id"] == "req-1"


async def _ignores_accepted_until_complete():
    client = FakeClient()

    async def inject():
        await asyncio.sleep(0)
        client.events.append({"type": "command_status", "request_id": "req-1", "status": "accepted"})
        async with client._event_condition:
            client._event_condition.notify_all()
        await asyncio.sleep(0)
        client.events.append({"type": "command_status", "request_id": "req-1", "status": "complete"})
        async with client._event_condition:
            client._event_condition.notify_all()

    task = asyncio.create_task(inject())
    result = await client.command_wait("move_joint", request_id="req-1", timeout=0.5)
    await task

    assert result["status"] == "complete"


async def _can_return_on_accepted_for_servo_follow():
    client = FakeClient()

    async def inject():
        await asyncio.sleep(0)
        client.events.append({"type": "command_status", "request_id": "req-1", "status": "accepted"})
        async with client._event_condition:
            client._event_condition.notify_all()

    task = asyncio.create_task(inject())
    result = await client.command_wait(
        "move_joint",
        request_id="req-1",
        timeout=0.5,
        terminal_only=False,
    )
    await task

    assert result["status"] == "accepted"


def test_command_wait_ignores_unrelated_motion_state_without_request_id():
    run(_ignores_unrelated_motion_state_without_request_id())


def test_command_wait_returns_matching_command_status():
    run(_returns_matching_command_status())


def test_command_wait_ignores_accepted_until_complete():
    run(_ignores_accepted_until_complete())


def test_command_wait_can_return_on_accepted_for_servo_follow():
    run(_can_return_on_accepted_for_servo_follow())


if __name__ == "__main__":
    test_command_wait_ignores_unrelated_motion_state_without_request_id()
    test_command_wait_returns_matching_command_status()
    test_command_wait_ignores_accepted_until_complete()
    test_command_wait_can_return_on_accepted_for_servo_follow()
    print("ROBOT_WS_CLIENT_OK")
