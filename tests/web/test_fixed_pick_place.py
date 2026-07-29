from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "web-control" / "scripts" / "fixed_pick_place.py"
SPEC = importlib.util.spec_from_file_location("fixed_pick_place", SCRIPT)
assert SPEC and SPEC.loader
fixed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixed)
sys.path.insert(0, str(SCRIPT.parent))
from teach_fixed_point import save_point  # noqa: E402


def config_dict():
    return {
        "joint_limits_deg": [
            [-162, 162],
            [-12, 201],
            [-183, 0],
            [-98, 98],
            [-98, 98],
            [-164, 164],
        ],
        "joint_max_speeds_deg_s": [300, 300, 300, 1000, 1000, 1000],
        "speed_scale": 0.05,
        "motion": {"min_time_s": 0.01, "timeout_s": 1, "settle_s": 0},
        "gripper": {
            "open_position": 1.0,
            "close_position": 0.0,
            "timeout_s": 1,
        },
        "waypoints": {
            name: [10.0, 20.0, -30.0, 5.0, -5.0, 10.0]
            for name in fixed.POINT_NAMES
        },
    }


def write_config(tmp_path: Path, data):
    path = tmp_path / "points.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class FakeBridge:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure
        self.closed_failed = None

    def connect(self):
        self.calls.append(("connect",))
        self.latest_joints_deg = [1, 2, -3, 4, 5, 6]
        return list(self.latest_joints_deg)

    def move(self, joints, **kwargs):
        self.calls.append(("move", list(joints), kwargs["source"]))
        if self.failure == kwargs["source"]:
            raise fixed.MotionTimeout("motion timeout")

    def set_gripper(self, position, timeout_s, **kwargs):
        self.calls.append(("gripper", position))
        if self.failure == "gripper":
            raise fixed.BridgeError("gripper failure")

    def adaptive_grasp(self, timeout_s, **kwargs):
        self.calls.append(("adaptive_gripper", kwargs))
        if self.failure == "gripper":
            raise fixed.BridgeError("gripper failure")

    def close(self, *, failed=False):
        self.closed_failed = failed


class FixedPickPlaceTests(unittest.TestCase):
    def test_normal_action_sequence(self):
        bridge = FakeBridge()
        runner = fixed.FixedPickPlaceRunner(
            bridge,
            config_dict(),
            "simulate",
            logging.getLogger("test"),
        )
        runner.run()
        actions = [call[0] for call in bridge.calls]
        self.assertEqual(
            actions,
            [
                "connect",
                "move",
                "move",
                "move",
                "gripper",
                "move",
                "move",
                "move",
                "gripper",
                "move",
                "move",
            ],
        )
        self.assertIs(bridge.closed_failed, False)

    def test_invalid_waypoints_are_rejected(self):
        cases = [
            (None, "has not been taught"),
            ([1, 2, 3], "exactly six"),
            ([0, 0, 0, 0, 0, 0], "all-zero"),
            ([200, 20, -30, 5, 5, 5], "outside"),
            ([float("nan"), 20, -30, 5, 5, 5], "NaN"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for point, message in cases:
                with self.subTest(point=point):
                    data = config_dict()
                    data["waypoints"]["pick"] = point
                    with self.assertRaisesRegex(fixed.ConfigurationError, message):
                        fixed.load_config(write_config(Path(directory), data))

    def test_motion_timeout_stops_sequence(self):
        bridge = FakeBridge("fixed_pick_place:pick")
        runner = fixed.FixedPickPlaceRunner(
            bridge,
            config_dict(),
            "simulate",
            logging.getLogger("test"),
        )
        with self.assertRaises(fixed.MotionTimeout):
            runner.run()
        self.assertIs(bridge.closed_failed, True)
        self.assertFalse(
            any(
                call[0] == "move" and call[2] == "fixed_pick_place:lift"
                for call in bridge.calls
            )
        )

    def test_gripper_failure_stops_sequence(self):
        bridge = FakeBridge("gripper")
        runner = fixed.FixedPickPlaceRunner(
            bridge,
            config_dict(),
            "simulate",
            logging.getLogger("test"),
        )
        with self.assertRaises(fixed.BridgeError):
            runner.run()
        self.assertIs(bridge.closed_failed, True)

    def test_user_abort_before_first_step(self):
        bridge = FakeBridge()
        runner = fixed.FixedPickPlaceRunner(
            bridge,
            config_dict(),
            "real",
            logging.getLogger("test"),
            confirm_each_step=True,
            confirm=lambda _prompt: "STOP",
        )
        with self.assertRaises(fixed.UserAbort):
            runner.run()
        self.assertEqual(bridge.calls, [("connect",)])
        self.assertIs(bridge.closed_failed, True)

    def test_dry_run_mode_uses_same_sequence_without_real_bridge(self):
        bridge = FakeBridge()
        runner = fixed.FixedPickPlaceRunner(
            bridge,
            config_dict(),
            "dry-run",
            logging.getLogger("test"),
        )
        runner.run()
        self.assertIs(bridge.closed_failed, False)

    def test_simple_ab_requires_only_home_a_b_and_moves_directly_a_to_b(self):
        data = config_dict()
        data["workflow"] = "simple_ab"
        data["demo"] = {
            "speed_scale": 0.03,
            "require_step_confirmation": True,
            "validated_real_cycles": 0,
        }
        data["waypoints"]["pick"] = None
        data["waypoints"]["lift"] = None
        data["waypoints"]["pre_place"] = None
        data["waypoints"]["retreat"] = None
        with tempfile.TemporaryDirectory() as directory:
            config = fixed.load_config(write_config(Path(directory), data))
        bridge = FakeBridge()
        runner = fixed.FixedPickPlaceRunner(
            bridge,
            config,
            "simulate",
            logging.getLogger("test"),
        )
        runner.run()
        sources = [
            call[2]
            for call in bridge.calls
            if call[0] == "move"
        ]
        self.assertEqual(
            sources,
            [
                "fixed_pick_place:pre_pick",
                "fixed_pick_place:place",
            ],
        )

    def test_home_transit_ab_moves_bottle_both_directions_via_home(self):
        data = config_dict()
        data["workflow"] = "home_transit_ab"
        data["gripper"]["grasp_position"] = 0.5
        data["waypoints"]["pick"] = None
        data["waypoints"]["lift"] = None
        data["waypoints"]["pre_place"] = None
        data["waypoints"]["retreat"] = None
        with tempfile.TemporaryDirectory() as directory:
            config = fixed.load_config(write_config(Path(directory), data))
        bridge = FakeBridge()
        fixed.FixedPickPlaceRunner(
            bridge,
            config,
            "simulate",
            logging.getLogger("test"),
        ).run()
        self.assertEqual(
            [call[2] for call in bridge.calls if call[0] == "move"],
            [
                "fixed_pick_place:home",
                "fixed_pick_place:pre_pick",
                "fixed_pick_place:a_up",
                "fixed_pick_place:b_up",
                "fixed_pick_place:place",
                "fixed_pick_place:b_up",
                "fixed_pick_place:home",
                "fixed_pick_place:b_up",
                "fixed_pick_place:place",
                "fixed_pick_place:b_up",
                "fixed_pick_place:a_up",
                "fixed_pick_place:pre_pick",
                "fixed_pick_place:a_up",
                "fixed_pick_place:home",
            ],
        )
        self.assertEqual(
            [call[1] for call in bridge.calls if call[0] == "gripper"],
            [1.0, 1.0, 1.0],
        )
        self.assertEqual(
            len([call for call in bridge.calls if call[0] == "adaptive_gripper"]),
            2,
        )

    def test_home_transit_ab_repeats_configured_cycles(self):
        data = config_dict()
        data["workflow"] = "home_transit_ab"
        data["demo"] = {"cycles": 3}
        for name in ("pick", "lift", "pre_place", "retreat"):
            data["waypoints"][name] = None
        with tempfile.TemporaryDirectory() as directory:
            config = fixed.load_config(write_config(Path(directory), data))
        bridge = FakeBridge()
        fixed.FixedPickPlaceRunner(
            bridge,
            config,
            "simulate",
            logging.getLogger("test"),
        ).run()
        self.assertEqual(
            len([call for call in bridge.calls if call[0] == "adaptive_gripper"]),
            6,
        )
        self.assertEqual(
            len([call for call in bridge.calls if call[0] == "move"]),
            42,
        )

    def test_motion_only_skips_adaptive_grasps(self):
        data = config_dict()
        data["workflow"] = "home_transit_ab"
        for name in ("pick", "lift", "pre_place", "retreat"):
            data["waypoints"][name] = None
        with tempfile.TemporaryDirectory() as directory:
            config = fixed.load_config(write_config(Path(directory), data))
        bridge = FakeBridge()
        fixed.FixedPickPlaceRunner(
            bridge,
            config,
            "simulate",
            logging.getLogger("test"),
            motion_only=True,
        ).run()
        self.assertFalse(
            any(call[0] == "adaptive_gripper" for call in bridge.calls)
        )

    def test_segment_jump_limit_rejects_unexpected_starting_pose(self):
        data = config_dict()
        data["workflow"] = "simple_ab"
        data["motion"]["max_segment_delta_deg"] = [10, 10, 10, 10, 10, 10]
        data["waypoints"]["place"] = [-20.0, 20.0, -30.0, 5.0, -5.0, 10.0]
        data["waypoints"]["pick"] = None
        data["waypoints"]["lift"] = None
        data["waypoints"]["pre_place"] = None
        data["waypoints"]["retreat"] = None
        with tempfile.TemporaryDirectory() as directory:
            config = fixed.load_config(write_config(Path(directory), data))
        bridge = FakeBridge()
        runner = fixed.FixedPickPlaceRunner(
            bridge,
            config,
            "simulate",
            logging.getLogger("test"),
        )
        with self.assertRaisesRegex(fixed.ConfigurationError, "segment jump rejected"):
            runner.run()
        self.assertIs(bridge.closed_failed, True)

    def test_keyboard_interrupt_runs_cleanup(self):
        bridge = FakeBridge()

        def interrupt(_prompt):
            raise KeyboardInterrupt

        runner = fixed.FixedPickPlaceRunner(
            bridge,
            config_dict(),
            "real",
            logging.getLogger("test"),
            confirm_each_step=True,
            confirm=interrupt,
        )
        with self.assertRaises(KeyboardInterrupt):
            runner.run()
        self.assertIs(bridge.closed_failed, True)

    def test_teach_point_backs_up_then_atomically_updates(self):
        data = config_dict()
        data["waypoints"] = {name: None for name in fixed.POINT_NAMES}
        taught = [12.5, 45.0, -60.0, 4.0, -3.0, 2.0]
        with tempfile.TemporaryDirectory() as directory:
            config_path = write_config(Path(directory), data)
            backup = save_point(config_path, "home", taught)
            self.assertTrue(backup.exists())
            previous = yaml.safe_load(backup.read_text(encoding="utf-8"))
            current = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertIsNone(previous["waypoints"]["home"])
            self.assertEqual(current["waypoints"]["home"], taught)

    @unittest.skipUnless(os.name == "posix", "fcntl lock is a Linux safety mechanism")
    def test_existing_bridge_rejects_second_control_process(self):
        bridge_path = ROOT / "web-control" / "server" / "startouch_bridge.py"
        bridge_spec = importlib.util.spec_from_file_location("lock_test_bridge", bridge_path)
        assert bridge_spec and bridge_spec.loader
        bridge_module = importlib.util.module_from_spec(bridge_spec)
        bridge_spec.loader.exec_module(bridge_module)
        first = bridge_module.RobotBridge()
        second = bridge_module.RobotBridge()
        try:
            first._acquire_control_lock()
            with self.assertRaisesRegex(RuntimeError, "already controlled"):
                second._acquire_control_lock()
        finally:
            first.shutdown()
            second.shutdown()


if __name__ == "__main__":
    unittest.main()
