"""No hardware SDK import/construction: test the real bridge with a fake arm."""
import importlib.util
import math
from pathlib import Path
import threading
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/robot/src"))
spec = importlib.util.spec_from_file_location("speed_bridge", ROOT / "services/robot/src/startouch_bridge.py")
bridge_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_module)

@pytest.mark.parametrize("kind", ["move_joint", "move_joint_path", "move_l", "go_home"])
def test_all_sdk_routes_ignore_short_time_and_use_capped_speed(monkeypatch, kind):
    events, calls = [], []
    done = threading.Event()
    monkeypatch.setattr(bridge_module, "SIMULATE", True)
    monkeypatch.setattr(bridge_module, "emit", lambda event, **data: (events.append((event, data)), done.set() if event == "command_complete" else None))
    monkeypatch.setattr(bridge_module.RobotBridge, "publish_state", lambda self, **kwargs: None)
    class Arm:
        def get_joint_positions(self): return [0.1, 0.1, -0.1, 0.1, 0.1, 0.1]
        def set_joint_waypoints(self, targets, **kwargs):
            calls.append(("joint", targets, kwargs))
            return 23.75
        def move_l(self, targets, **kwargs):
            calls.append(("linear", targets, kwargs))
            return 23.75
    robot = bridge_module.RobotBridge()
    robot.arm = Arm()
    robot.connected = robot.state_ready = True
    robot.last_valid_joints = [0.1, 0.1, -0.1, 0.1, 0.1, 0.1]
    command = {"cmd": kind, "joints_rad": [0.2,0.2,-0.2,0.2,0.2,0.2],
               "waypoints_rad": [[0.2,0.2,-0.2,0.2,0.2,0.2]],
               "position": [0.4,0,0.3], "euler": [0,0,0],
               "time_sec": 0.001, "speed_percent": 1, "request_id": "speed-test"}
    try:
        if kind == "move_l": robot.move_linear(command)
        elif kind == "go_home": robot.go_home("speed-test")
        else: robot.enqueue_motion(command)
        assert done.wait(2), events
        assert calls[0][2]["speed_percent"] == 0.05
        assert "time_sec" not in calls[0][2]
        assert calls[0][0] == ("linear" if kind == "move_l" else "joint")
        complete = next(data for name, data in events if name == "command_complete")
        assert complete["duration_sec"] == 23.75
        assert complete["request_id"] == "speed-test"
    finally:
        robot.shutdown_requested.set()
        robot.motion_thread.join(1)
        robot.state_thread.join(1)

def test_runtime_patch_only_changes_speed_field_and_is_reversible(tmp_path):
    import subprocess
    original = ("kinematics:\n  tool: unchanged\njoint_trajectory:\n"
                "  max_vel_limits: [5.5, 5.5, 5.5, 20.9, 20.9, 20.9]\n"
                "  max_acc_limits: [500,500,800,2000,2000,2000]\n")
    directory = tmp_path / "local/sdk/startouch/src/config"
    directory.mkdir(parents=True)
    config = directory / "robot_kinematics.yaml"
    config.write_text(original)
    patch = ROOT / "services/robot/config/sdk-joint-speed.patch"
    subprocess.run(["git", "apply", "--unidiff-zero", str(patch)], cwd=tmp_path, check=True)
    new = config.read_text()
    changed = [line for line in new.splitlines() if "max_vel_limits:" in line][0]
    limits = __import__("json").loads(changed.split(":", 1)[1])
    assert [math.degrees(v) * 0.05 for v in limits] == pytest.approx([15,15,15,50,50,50])
    assert new.replace(changed, original.splitlines()[3]) == original
    subprocess.run(["git", "apply", "--unidiff-zero", "--reverse", str(patch)], cwd=tmp_path, check=True)
    assert config.read_text() == original

def test_bad_runtime_reference_is_rejected_without_sdk_construction(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "services/robot/src"))
    from joint_speed_policy import validate_sdk_speed_reference
    sdk = tmp_path / "sdk"
    config = sdk / "src/config/robot_kinematics.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("joint_trajectory:\n  max_vel_limits: [5.5,5.5,5.5,20.9,20.9,20.9]\n")
    with pytest.raises(ValueError, match="speed reference"):
        validate_sdk_speed_reference(str(sdk))
