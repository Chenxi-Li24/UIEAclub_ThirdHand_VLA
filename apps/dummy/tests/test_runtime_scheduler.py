import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.config import load_config
from dummy.person_follow.runtime import PersonFollowRuntime
from dummy.tracker import Target
from dummy.wake_word import WakeWordDetector


class Guard:
    def check(self, joints):
        return True, "test geometry"


class Adapter:
    def __init__(self):
        self.joints = [0.0] * 6
        self.sent = []
        self.closed = False
        self.on_idle = None
        self.on_send = None
        self.depth = 0
        self.max_depth = 0

    async def wait_idle(self, timeout=35):
        if self.on_idle:
            callback, self.on_idle = self.on_idle, None
            callback()
        return SimpleNamespace(joints_deg=list(self.joints))

    def _validate(self, joints):
        return list(joints)

    async def send_joint_target(self, target, **kwargs):
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)
        try:
            if self.on_send:
                callback, self.on_send = self.on_send, None
                callback()
            if kwargs.get("before_send"):
                target = kwargs["before_send"](SimpleNamespace(joints_deg=list(self.joints)))
                if target is None:
                    return False
            await asyncio.sleep(0)
            self.sent.append(list(target))
            self.joints = list(target)
            return True
        finally:
            self.depth -= 1

    async def close(self):
        self.closed = True


def target(u=520, v=240, *, age=0, kind="person_lock"):
    return Target(True, u, v, 640, 480, 0.9, kind, time.time() - age)


def runtime(adapter=None):
    cfg = load_config()
    return PersonFollowRuntime(adapter, config=cfg, guard=Guard())


def test_busy_wait_and_final_send_both_recompute_from_latest_target():
    async def scenario():
        adapter = Adapter()
        rt = runtime(adapter)
        rt.publish(target(100))
        adapter.on_idle = lambda: rt.publish(target(520))
        assert await rt.step()
        assert adapter.sent[0][0] < 0  # latest target is right of center
        adapter.on_send = lambda: rt.publish(target(100))
        rt.publish(target(520))
        assert await rt.step()
        assert adapter.sent[1][0] > adapter.sent[0][0]
        for joints in adapter.sent:
            assert joints[1:3] == [0, 0] and joints[4:] == [0, 0]
            assert abs(joints[3]) <= 35
    asyncio.run(scenario())


@pytest.mark.parametrize("age,kind", [(1, "person_lock"), (0, "person_lock_hold"), (-1, "person_lock")])
def test_stale_held_and_future_targets_never_move(age, kind):
    async def scenario():
        adapter = Adapter()
        rt = runtime(adapter)
        rt.publish(target(age=age, kind=kind))
        assert not await rt.step()
        assert adapter.sent == []
    asyncio.run(scenario())


def test_no_new_frame_no_extra_command_and_no_idle_breathing():
    async def scenario():
        adapter = Adapter()
        rt = runtime(adapter)
        assert not await rt.step()
        rt.publish(target())
        assert await rt.step()
        count = len(adapter.sent)
        assert not await rt.step()
        assert len(adapter.sent) == count
        assert load_config()["idle"]["enabled"] is False
    asyncio.run(scenario())


def test_keyword_all_joints_exclusive_then_follow_resumes():
    async def scenario():
        adapter = Adapter()
        rt = runtime(adapter)
        rt.config["gestures"]["custom"] = {"keyframes": [
            {"t": 0.3, "offset_deg": [1, 2, -3, 4, 5, 6]},
            {"t": 0.6, "offset_deg": [0, 0, 0, 0, 0, 0]},
        ]}
        rt.publish(target())
        assert rt.queue_keyword("custom")
        assert await rt.step()
        assert adapter.sent == [[1, 2, -3, 4, 5, 6], [0] * 6]
        assert await rt.step()
        assert adapter.max_depth == 1
    asyncio.run(scenario())


def test_shutdown_starts_no_new_command_and_closes_owned_client_only():
    async def scenario():
        adapter = Adapter()
        rt = runtime(adapter)
        adapter.on_send = rt.request_stop
        rt.publish(target())
        await rt.run(max_steps=10)
        assert rt.mode == "STOPPED" and adapter.closed
        assert adapter.sent == []
        assert not rt._keywords
    asyncio.run(scenario())


def test_old_keyword_is_discarded():
    async def scenario():
        adapter = Adapter()
        rt = runtime(adapter)
        rt.queue_keyword("nod", received_at=time.monotonic() - 10)
        assert not await rt.step()
        assert adapter.sent == []
    asyncio.run(scenario())


def test_final_keyword_protocol_dedupe_and_negation():
    detector = WakeWordDetector({})
    message = {"type": "transcript.final", "messageId": "1", "payload": {"text": "ThirdHand nod"}}
    assert detector.transcript_event(message)["action"] == "nod"
    assert detector.transcript_event(message) is None
    assert detector.transcript_event({**message, "type": "transcript.partial"}) is None
    assert detector._action("do not nod") is None
    assert detector._action("\u4e0d\u8981\u70b9\u5934") is None
    assert detector._action("\u70b9\u5934") == "nod"
