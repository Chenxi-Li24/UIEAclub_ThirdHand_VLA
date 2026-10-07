import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.robot_ws_client import RobotWebSocketClient


class FakeClient(RobotWebSocketClient):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.response = None

    async def command(self, cmd, **kwargs):
        self.sent.append((cmd, kwargs))
        if self.response:
            self._receive({**self.response, "request_id": kwargs["request_id"]})


def test_completion_survives_full_event_ring_and_inline_reply():
    async def scenario():
        client = FakeClient()
        for i in range(250):
            client._receive({"type": "log", "i": i})
        client.response = {"type": "command_status", "status": "complete"}
        reply = await client.command_wait("move_joint", request_id="req")
        assert reply["status"] == "complete"
        assert len(client.events) == 200
        assert not client._pending
    asyncio.run(scenario())


@pytest.mark.parametrize("terminal_only,expected", [(True, "complete"), (False, "accepted")])
def test_acceptance_and_completion_are_distinct(terminal_only, expected):
    async def scenario():
        client = FakeClient()
        async def inject():
            await asyncio.sleep(0)
            client._receive({"type": "command_status", "request_id": "req", "status": "accepted"})
            await asyncio.sleep(0)
            client._receive({"type": "command_status", "request_id": "req", "status": "complete"})
        producer = asyncio.create_task(inject())
        reply = await client.command_wait("move_joint", request_id="req", terminal_only=terminal_only)
        await producer
        assert reply["status"] == expected
    asyncio.run(scenario())


def test_uncorrelated_errors_and_other_requests_do_not_complete_command():
    async def scenario():
        client = FakeClient()
        async def inject():
            await asyncio.sleep(0)
            for event in ({"type": "error"}, {"type": "error", "request_id": "other"},
                          {"type": "motion_state", "stateName": "MOVING"}):
                client._receive(event)
        producer = asyncio.create_task(inject())
        assert await client.command_wait("move_joint", request_id="req", timeout=0.02) is None
        await producer
        assert not client._pending
    asyncio.run(scenario())


def test_multiple_inflight_requests_and_close_failures():
    async def scenario():
        client = FakeClient()
        tasks = [asyncio.create_task(client.command_wait("move_joint", request_id=str(i))) for i in range(2)]
        await asyncio.sleep(0)
        client._receive({"type": "command_status", "request_id": "1", "status": "complete"})
        assert (await tasks[1])["request_id"] == "1"
        await client.close()
        with pytest.raises(ConnectionError):
            await tasks[0]
        assert not client._pending
    asyncio.run(scenario())


def test_send_failure_is_never_retried():
    async def scenario():
        client = RobotWebSocketClient()
        class BrokenSocket:
            attempts = 0
            async def send(self, _payload):
                self.attempts += 1
                raise OSError("ambiguous send")
        client.ws = BrokenSocket()
        with pytest.raises(OSError):
            await client.command("move_joint", joints_deg=[0] * 6)
        assert client.ws.attempts == 1
    asyncio.run(scenario())


def test_nonfinite_feedback_cannot_authorize_motion():
    client = FakeClient()
    client._receive({"type": "robot_state", "joints": [0, 0, 0, float("nan"), 0, 0], "stateName": "IDLE"})
    assert not client.snapshot.state_ready
