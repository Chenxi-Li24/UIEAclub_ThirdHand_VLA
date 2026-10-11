"""Stdlib-only regression checks: no hardware SDK or network dependencies."""
import importlib.util
import math
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(os.environ.get("ROBOT_OVERLAY_SRC", ROOT / "services/robot/src"))
sys.path.insert(0, str(SOURCE))
from joint_speed_policy import bounded_speed_percent
from continuous_follow import ContinuousFollow

spec = importlib.util.spec_from_file_location("ceiling_bridge", SOURCE / "startouch_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

class JointSpeedCeilingTests(unittest.TestCase):
    def test_follow_keeps_original_velocity_acceleration_and_jerk_at_global_ten_percent(self):
        follow = ContinuousFollow(None, .1)
        self.assertAlmostEqual(math.degrees(follow.speed[3]), 50)
        self.assertAlmostEqual(math.degrees(follow.acceleration[3]), 50 / .3)
        self.assertAlmostEqual(math.degrees(follow.jerk[3]), 50 / .3 / .1)
        self.assertAlmostEqual(math.degrees(follow.acceleration[0]), 15 / .3)

    def test_requested_ten_percent_is_not_silently_clamped_to_five(self):
        self.assertEqual(bounded_speed_percent(.1), .1)
        self.assertEqual(bounded_speed_percent(1), .1)
        self.assertEqual(bounded_speed_percent(), .05)

    def test_sdk_receives_ten_percent_and_horizontal_precision(self):
        calls, done = [], threading.Event()
        class Arm:
            def get_joint_positions(self): return [.1,.1,-.1,.1,.1,.1]
            def move_l(self, targets, **kwargs): calls.append(kwargs); return 1
        def emit(kind, **data):
            if kind == "command_complete": done.set()
        with patch.object(bridge, "SIMULATE", True), patch.object(bridge, "SPEED_PERCENT", .1), \
                patch.object(bridge, "emit", emit), patch.object(bridge.RobotBridge, "publish_state", lambda self, **kwargs: None):
            robot = bridge.RobotBridge()
            robot.arm = Arm(); robot.connected = robot.state_ready = True
            robot.last_valid_joints = [.1,.1,-.1,.1,.1,.1]
            try:
                robot.move_linear({"position":[.4,0,.3],"euler":[0,0,0],"speed_percent":.1,
                    "position_tolerance_m":.015,"orientation_tolerance_rad":.05,"request_id":"horizontal-speed"})
                self.assertTrue(done.wait(2))
                self.assertEqual(calls[0]["speed_percent"], .1)
                self.assertEqual(calls[0]["position_tolerance_m"], .015)
                self.assertEqual(calls[0]["orientation_tolerance_rad"], .05)
            finally:
                robot.shutdown_requested.set(); robot.motion_thread.join(1); robot.state_thread.join(1)

if __name__ == "__main__": unittest.main()
