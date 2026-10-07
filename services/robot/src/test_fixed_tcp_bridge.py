"""No-motion check: demo uses the 3000 bridge's existing arm object."""

import queue
import sys
import threading
from types import ModuleType, SimpleNamespace

import startouch_bridge as module


class FakeArm:
    def get_joint_positions(self):
        return [0.0] * 6


def test_existing_arm_only():
    bridge = module.RobotBridge.__new__(module.RobotBridge)
    bridge.arm = FakeArm()
    bridge.connected = True
    bridge.state_ready = True
    bridge.motion_active = False
    bridge.last_valid_joints = [0.0] * 6
    bridge.expected_motion_target = None
    bridge.arm_lock = threading.RLock()
    bridge.motion_queue = queue.Queue(maxsize=1)
    bridge.stop_requested = threading.Event()
    bridge.shutdown_requested = threading.Event()
    bridge._emit_joint_log = lambda *args, **kwargs: None
    events = []
    fake_demo = ModuleType("demo")
    fake_demo.DemoConfig = lambda **kwargs: kwargs

    class FakeDemo:
        def __init__(self, arm, *, config, log_dir):
            assert arm is bridge.arm
            assert config["execute"] is False
            assert config["fixed_xyz"] == [0.48, 0, 0.36]
            self.logger = SimpleNamespace(close=lambda: events.append("logger_closed"))

        def run_forever(self):
            events.append("used_existing_arm")
            bridge.connected = False
            bridge.shutdown_requested.set()

    fake_demo.FixedTcpDemo = FakeDemo
    old_demo = sys.modules.get("demo")
    old_emit = module.emit
    sys.modules["demo"] = fake_demo
    module.emit = lambda event, **kwargs: events.append((event, kwargs))
    try:
        bridge.enqueue_fixed_tcp_demo({"request_id": "demo", "execute": False,
            "fixed_xyz": [0.48, 0, 0.36], "use_current_tcp_xyz": False,
            "max_cone_deg": 50, "duration_sec": 60})
        assert any(isinstance(item, tuple) and item[0] == "command_accepted" for item in events)
        bridge._motion_loop()
        assert "used_existing_arm" in events
        assert "logger_closed" in events
        assert any(isinstance(event, tuple) and event[0] == "command_complete" for event in events)
    finally:
        module.emit = old_emit
        if old_demo is None:
            del sys.modules["demo"]
        else:
            sys.modules["demo"] = old_demo


if __name__ == "__main__":
    test_existing_arm_only()
