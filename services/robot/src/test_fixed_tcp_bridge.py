"""No-motion check: demo uses the 3000 bridge's existing arm object."""

import queue
import sys
import threading
from types import ModuleType, SimpleNamespace

import startouch_bridge as module


class FakeArm:
    def get_joint_positions(self):
        return [0.0] * 6


def run_fixture(execute=False):
    bridge = module.RobotBridge.__new__(module.RobotBridge)
    bridge.arm = FakeArm()
    bridge.connected = True
    bridge.state_ready = True
    bridge.motion_active = False
    bridge.connection_generation = 0
    bridge.active_motion_cancel = None
    bridge.last_valid_joints = [0.0] * 6
    bridge.expected_motion_target = None
    bridge.arm_lock = threading.RLock()
    bridge.motion_queue = queue.Queue(maxsize=1)
    bridge.stop_requested = threading.Event()
    bridge.shutdown_requested = threading.Event()
    bridge._emit_joint_log = lambda *args, **kwargs: None
    events = []
    seen_config = {}
    fake_demo = ModuleType("demo")
    fake_demo.DemoConfig = lambda **kwargs: kwargs

    class FakeDemo:
        def __init__(self, arm, *, config, log_dir):
            assert arm is bridge.arm
            seen_config.update(config)
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
        bridge.enqueue_fixed_tcp_demo({"request_id": "demo", "execute": execute,
            "fixed_xyz": [0.48, 0, 0.36], "use_current_tcp_xyz": False,
            "max_cone_deg": 50, "duration_sec": 60})
        assert any(isinstance(item, tuple) and item[0] == "command_accepted" for item in events)
        bridge._motion_loop()
        assert "used_existing_arm" in events
        assert "logger_closed" in events
        assert seen_config["execute"] is (execute and not module.DRY_RUN)
        assert seen_config["execute_speed_percent"] == module.SPEED_PERCENT
        assert any(isinstance(event, tuple) and event[0] == "command_complete" for event in events)
    finally:
        module.emit = old_emit
        if old_demo is None:
            del sys.modules["demo"]
        else:
            sys.modules["demo"] = old_demo


def test_existing_arm_only():
    run_fixture()


def test_dry_run_environment_cannot_be_overridden():
    old_dry_run = module.DRY_RUN
    module.DRY_RUN = True
    try:
        run_fixture(execute=True)
    finally:
        module.DRY_RUN = old_dry_run


def test_demo_preserves_a_lower_service_speed_scale():
    old_speed = module.SPEED_PERCENT
    module.SPEED_PERCENT = 0.02
    try:
        run_fixture()
    finally:
        module.SPEED_PERCENT = old_speed


def cancellation_fixture():
    bridge = module.RobotBridge.__new__(module.RobotBridge)
    bridge.arm = FakeArm()
    bridge.connected = bridge.state_ready = True
    bridge.motion_active = False
    bridge.connection_generation = 0
    bridge.active_motion_cancel = None
    bridge.last_valid_joints = [0.0] * 6
    bridge.expected_motion_target = None
    bridge.arm_lock = threading.RLock()
    bridge.motion_queue = queue.Queue(maxsize=1)
    bridge.stop_requested = threading.Event()
    bridge.shutdown_requested = threading.Event()
    bridge.control_lock_file = None
    bridge.follow = None
    bridge._emit_joint_log = lambda *args, **kwargs: None
    bridge._acquire_control_lock = lambda: None
    bridge._read_can_rx_packets = lambda: 0
    bridge._wait_for_stable_state = lambda *args: {"joints": [0.0] * 6}
    bridge._record_can_rx = lambda *args: None
    bridge._emit_snapshot = lambda *args: None
    bridge.publish_state = lambda *args, **kwargs: None
    bridge.arm.cleanup = lambda: None
    return bridge


def demo_command():
    return {"request_id": "cancel-demo", "execute": False,
            "fixed_xyz": [0.48, 0, 0.36], "use_current_tcp_xyz": False,
            "max_cone_deg": 50, "duration_sec": 60}


def test_queued_demo_cancellation_has_exactly_one_terminal_reply():
    bridge = cancellation_fixture()
    events = []
    old_emit = module.emit
    module.emit = lambda event, **kwargs: events.append((event, kwargs))
    try:
        bridge.enqueue_fixed_tcp_demo(demo_command())
        bridge.disconnect("software_stop")
        terminal = [data for kind, data in events if kind == "error" and data.get("request_id") == "cancel-demo"]
        assert len(terminal) == 1, events
        assert terminal[0]["code"] == "motion_cancelled"
        assert bridge.motion_queue.empty()
    finally:
        module.emit = old_emit


def test_blocked_demo_cancellation_cannot_be_revived_by_reconnect():
    bridge = cancellation_fixture()
    entered, resume = threading.Event(), threading.Event()
    observed = {}
    constructed = []
    fake_demo = ModuleType("demo")
    fake_demo.DemoConfig = lambda **kwargs: kwargs

    class BlockingDemo:
        def __init__(self, arm, **kwargs):
            self.logger = SimpleNamespace(close=lambda: None)

        def run_forever(self):
            observed["cancel"] = self.stop_requested
            entered.set()
            assert resume.wait(3)
            observed["cancelled"] = self.stop_requested.is_set()
            bridge.shutdown_requested.set()
            if observed["cancelled"]:
                raise RuntimeError("cancelled fake demo")
            observed["sent_after_stop"] = True

    fake_demo.FixedTcpDemo = BlockingDemo
    old_demo, old_emit = sys.modules.get("demo"), module.emit
    old_simulate, old_arm = module.SIMULATE, module.SimulatedArm
    sys.modules["demo"] = fake_demo
    module.emit = lambda *args, **kwargs: None
    module.SIMULATE = True
    module.SimulatedArm = lambda: constructed.append("new arm") or FakeArm()
    thread = threading.Thread(target=bridge._motion_loop)
    try:
        bridge.enqueue_fixed_tcp_demo(demo_command())
        thread.start()
        assert entered.wait(3)
        bridge.disconnect("software_stop")
        bridge.connect()
        assert not constructed, "must not construct a new arm while an old worker is unfinished"
        bridge.stop_requested.clear()
        assert observed["cancel"].is_set(), "per-run cancellation must not share a reusable event"
    finally:
        resume.set()
        thread.join(3)
        module.SIMULATE, module.SimulatedArm = old_simulate, old_arm
        module.emit = old_emit
        if old_demo is None:
            del sys.modules["demo"]
        else:
            sys.modules["demo"] = old_demo
    assert not thread.is_alive()
    assert observed["cancelled"] and not observed.get("sent_after_stop")


if __name__ == "__main__":
    test_existing_arm_only()
    test_dry_run_environment_cannot_be_overridden()
    test_demo_preserves_a_lower_service_speed_scale()
    test_queued_demo_cancellation_has_exactly_one_terminal_reply()
    test_blocked_demo_cancellation_cannot_be_revived_by_reconnect()
