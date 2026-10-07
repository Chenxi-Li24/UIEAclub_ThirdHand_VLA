import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.robot_ws_client import RobotWebSocketClient


class FakeClient(RobotWebSocketClient):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def command(self, cmd, **kwargs):
        self.sent.append((cmd, kwargs))


def run(coro):
    return asyncio.run(coro)


async def test_command_wait_ignores_unrelated_motion_state_without_request_id_async():
    client = FakeClient()
    client.events.append({"type": "motion_state", "stateName": "MOVING"})

    result = await client.command_wait("move_joint", request_id="req-1", timeout=0.01)

    assert result is None


async def test_command_wait_returns_matching_command_status_async():
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


async def test_command_wait_ignores_accepted_until_complete_async():
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


async def test_command_wait_can_return_on_accepted_for_servo_follow_async():
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


if __name__ == "__main__":
    run(test_command_wait_ignores_unrelated_motion_state_without_request_id_async())
    run(test_command_wait_returns_matching_command_status_async())
    run(test_command_wait_ignores_accepted_until_complete_async())
    run(test_command_wait_can_return_on_accepted_for_servo_follow_async())
    print("ROBOT_WS_CLIENT_OK")
