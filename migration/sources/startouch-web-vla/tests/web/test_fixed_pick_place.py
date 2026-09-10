from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

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

    def move_path(self, waypoints, **kwargs):
        self.calls.append(
            ("move_path", [list(point) for point in waypoints], kwargs["source"])
        )
        self.latest_joints_deg = list(waypoints[-1])

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
    def run_launcher_mode_validation(self, **overrides):
        env = os.environ.copy()
        env.update(
            {
                "DEMO_MODE_VALIDATE_ONLY": "1",
                "DEMO_PREFLIGHT_ONLY": "1",
                **overrides,
            }
        )
        return subprocess.run(
            ["bash", str(ROOT / "scripts" / "demo_fixed_pick_place.sh")],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_full_real_config_simulation_completes_with_confirmations(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--simulate",
                "--config",
                str(ROOT / "configs" / "tasks" / "fixed_pick_place.yaml"),
                "--speed-scale",
                "1.0",
                "--confirm-each-step",
            ],
            input="\n" * 40,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("CYCLE 1/1 COMPLETE", output)
        self.assertIn("STATE COMPLETE", output)
        self.assertEqual(output.count("AWAITING_CONFIRMATION="), 20)

    def test_automatic_three_cycle_simulation_runs_60_stages_without_input(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--simulate",
                "--config",
                str(ROOT / "configs" / "tasks" / "fixed_pick_place.yaml"),
                "--speed-scale",
                "1.0",
                "--cycles",
                "3",
                "--automatic-three-cycle",
            ],
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("CYCLE 3/3 COMPLETE", output)
        self.assertEqual(output.count("AWAITING_CONFIRMATION="), 0)

    def test_automatic_real_mode_requires_exactly_three_cycles(self):
        for cycles in (1, 2, 4):
            with self.subTest(cycles=cycles):
                data = config_dict()
                data["demo"] = {
                    "cycles": 1,
                    "validated_real_cycles": 0,
                    "require_step_confirmation": True,
                }
                with self.assertRaisesRegex(
                    fixed.ConfigurationError,
                    "--automatic-three-cycle requires --cycles 3",
                ):
                    fixed.apply_execution_overrides(
                        data,
                        mode="real",
                        cycles=cycles,
                        automatic_three_cycle=True,
                        confirm_each_step=False,
                    )

    def test_automatic_real_mode_rejects_step_confirmation(self):
        data = config_dict()
        data["demo"] = {
            "cycles": 1,
            "validated_real_cycles": 0,
            "require_step_confirmation": True,
        }
        with self.assertRaisesRegex(
            fixed.ConfigurationError,
            "--automatic-three-cycle cannot use --confirm-each-step",
        ):
            fixed.apply_execution_overrides(
                data,
                mode="real",
                cycles=3,
                automatic_three_cycle=True,
                confirm_each_step=True,
            )

    def test_manual_real_mode_still_requires_confirmation(self):
        data = config_dict()
        data["demo"] = {
            "cycles": 1,
            "validated_real_cycles": 0,
            "require_step_confirmation": True,
        }
        with self.assertRaisesRegex(
            fixed.ConfigurationError,
            "real mode requires --confirm-each-step",
        ):
            fixed.apply_execution_overrides(
                data,
                mode="real",
                cycles=None,
                automatic_three_cycle=False,
                confirm_each_step=False,
            )
        fixed.apply_execution_overrides(
            data,
            mode="real",
            cycles=None,
            automatic_three_cycle=False,
            confirm_each_step=True,
        )

    def test_resource_guard_matches_executables_not_diagnostic_text(self):
        guard = ROOT / "scripts" / "fixed_pick_place_resource_guard.sh"

        def classified(argv):
            with tempfile.TemporaryDirectory() as directory:
                proc = Path(directory) / "123"
                proc.mkdir()
                (proc / "cmdline").write_bytes(
                    b"\0".join(value.encode("utf-8") for value in argv) + b"\0"
                )
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; is_robot_controller_process "$2"',
                        "resource-guard-test",
                        str(guard),
                        str(proc),
                    ],
                    check=False,
                )
                return result.returncode == 0

        diagnostic = [
            "bash",
            "-c",
            (
                "grep -nE 'ros|colcon' ~/.bashrc; "
                "find /usr /opt -type f -name ros2 -print"
            ),
        ]
        self.assertFalse(classified(diagnostic))
        self.assertTrue(
            classified(
                [
                    "/home/nieqingcao/miniconda3/bin/python",
                    "-u",
                    (
                        "/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-"
                        "fixed-pick-place/web-control/server/startouch_bridge.py"
                    ),
                ]
            )
        )
        self.assertTrue(classified(["node", "proxy.js"]))
        self.assertTrue(classified(["/opt/ros/noetic/bin/roscore"]))
        self.assertFalse(
            classified(
                [
                    "/usr/bin/python3",
                    "/opt/ros/galactic/bin/ros2",
                    "launch",
                    "xv_sdk_ros2",
                    "xv_sdk_node_launch.py",
                ]
            )
        )
        self.assertTrue(
            classified(
                [
                    "/usr/bin/python3",
                    "/opt/ros/galactic/bin/ros2",
                    "launch",
                    "robot_bringup",
                    "arm_control.launch.py",
                ]
            )
        )

    def test_worktree_guard_ignores_cwd_only_but_detects_open_files(self):
        guard = ROOT / "scripts" / "fixed_pick_place_resource_guard.sh"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            worktree = base / "worktree"
            worktree.mkdir()
            proc = base / "123"
            proc.mkdir()
            (proc / "fd").mkdir()
            (proc / "cwd").symlink_to(worktree, target_is_directory=True)

            def is_using_files():
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        (
                            'source "$1"; '
                            'process_uses_worktree_files "$2" "$3"'
                        ),
                        "worktree-guard-test",
                        str(guard),
                        str(proc),
                        str(worktree),
                    ],
                    check=False,
                )
                return result.returncode == 0

            self.assertFalse(is_using_files())
            active_file = worktree / "active.yaml"
            active_file.write_text("active", encoding="utf-8")
            (proc / "fd" / "3").symlink_to(active_file)
            self.assertTrue(is_using_files())

    def test_final_docs_include_exact_launch_commands_and_dashboard(self):
        required = [
            "bash scripts/demo_fixed_pick_place.sh",
            "bash scripts/open_fixed_pick_place_control.sh",
        ]
        for relative in ("README.md", "docs/fixed_pick_place_audit.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(document=relative):
                for command in required:
                    self.assertIn(command, text)

    def test_demo_launcher_forwards_signals_to_owned_runner(self):
        script = (ROOT / "scripts" / "demo_fixed_pick_place.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("trap forward_stop INT TERM", script)
        self.assertIn('kill -INT "$runner_pid"', script)
        self.assertIn('"$PYTHON" "${runner_args[@]}" <&0 &', script)

    def test_launcher_accepts_only_the_fixed_automatic_tuple(self):
        result = self.run_launcher_mode_validation(
            DEMO_RUN_MODE="automatic-three-cycle",
            DEMO_CYCLES="3",
            DEMO_CONFIRM_EACH_STEP="0",
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("RUN_MODE=automatic-three-cycle", output)
        self.assertIn("CYCLES=3", output)
        self.assertIn("REQUIRE_STEP_CONFIRMATION=0", output)
        self.assertIn("DEMO_MODE_VALIDATION_OK", output)

    def test_launcher_rejects_invalid_automatic_tuples_before_preflight(self):
        cases = [
            {
                "DEMO_RUN_MODE": "unknown",
                "DEMO_CYCLES": "3",
                "DEMO_CONFIRM_EACH_STEP": "0",
            },
            {
                "DEMO_RUN_MODE": "automatic-three-cycle",
                "DEMO_CYCLES": "2",
                "DEMO_CONFIRM_EACH_STEP": "0",
            },
            {
                "DEMO_RUN_MODE": "automatic-three-cycle",
                "DEMO_CYCLES": "3",
                "DEMO_CONFIRM_EACH_STEP": "1",
            },
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                result = self.run_launcher_mode_validation(**overrides)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn("FAILED_STAGE=MODE_CHECK", output)
                self.assertNotIn("RUN_COMMAND=", output)

    def test_launcher_rejects_automatic_overrides_in_manual_mode(self):
        result = self.run_launcher_mode_validation(
            DEMO_RUN_MODE="manual",
            DEMO_CYCLES="3",
            DEMO_CONFIRM_EACH_STEP="0",
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("FAILED_STAGE=MODE_CHECK", output)
        self.assertNotIn("RUN_COMMAND=", output)

    def test_interpolate_joint_path_bounds_every_segment(self):
        path = fixed.interpolate_joint_path(
            [0.0] * 6,
            [25.0, -5.0, 0.0, 0.0, 0.0, 0.0],
            12.0,
        )
        self.assertEqual(path[-1], [25.0, -5.0, 0.0, 0.0, 0.0, 0.0])
        previous = [0.0] * 6
        for point in path:
            self.assertLessEqual(
                max(abs(goal - start) for start, goal in zip(previous, point)),
                12.0,
            )
            previous = point

    def test_real_closed_loop_submits_one_path_command(self):
        data = config_dict()
        data["motion"]["execution_chunk_deg"] = 12.0
        data["motion"]["final_target_tolerance_deg"] = 1.2
        bridge = FakeBridge()
        bridge.latest_joints_deg = [0.0] * 6
        runner = fixed.FixedPickPlaceRunner(
            bridge,
            data,
            "real",
            logging.getLogger("test"),
        )
        runner._move_closed_loop(
            "a_up",
            [25.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        self.assertEqual([call[0] for call in bridge.calls], ["move_path"])
        self.assertEqual(len(bridge.calls[0][1]), 3)

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

    def test_verified_30_percent_speed_is_allowed_and_remains_the_hard_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory)

            at_limit = config_dict()
            at_limit["speed_scale"] = 0.30
            at_limit["demo"] = {"speed_scale": 0.30}
            loaded = fixed.load_config(write_config(config_path, at_limit))
            self.assertEqual(loaded["speed_scale"], 0.30)
            self.assertEqual(loaded["demo"]["speed_scale"], 0.30)

            for field in ("speed_scale", "demo.speed_scale"):
                with self.subTest(field=field):
                    above_limit = config_dict()
                    above_limit["demo"] = {"speed_scale": 0.30}
                    if field == "speed_scale":
                        above_limit["speed_scale"] = 0.301
                    else:
                        above_limit["demo"]["speed_scale"] = 0.301
                    with self.assertRaisesRegex(
                        fixed.ConfigurationError, r"\(0, 0\.30\]"
                    ):
                        fixed.load_config(write_config(config_path, above_limit))

    def test_current_manual_and_automatic_demo_speed_is_15_percent(self):
        config = fixed.load_config(
            ROOT / "configs" / "tasks" / "fixed_pick_place.yaml"
        )
        self.assertEqual(config["speed_scale"], 0.15)
        self.assertEqual(config["demo"]["speed_scale"], 0.15)
        javascript = (
            ROOT / "web-control" / "demo" / "demo.js"
        ).read_text(encoding="utf-8")
        self.assertIn("15% 速度自动执行 3 次", javascript)

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

    def test_closed_confirmation_channel_is_a_clean_user_abort(self):
        bridge = FakeBridge()

        def closed_channel(_prompt):
            raise EOFError("closed")

        runner = fixed.FixedPickPlaceRunner(
            bridge,
            config_dict(),
            "real",
            logging.getLogger("test"),
            confirm_each_step=True,
            confirm=closed_channel,
        )
        with self.assertRaisesRegex(
            fixed.UserAbort,
            "confirmation channel closed",
        ):
            runner.run()
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
                "fixed_pick_place:a_up",
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
            45,
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

    def test_bridge_continuous_path_calls_sdk_once(self):
        bridge_path = ROOT / "web-control" / "server" / "startouch_bridge.py"
        bridge_spec = importlib.util.spec_from_file_location(
            "continuous_path_bridge",
            bridge_path,
        )
        assert bridge_spec and bridge_spec.loader
        bridge_module = importlib.util.module_from_spec(bridge_spec)
        bridge_spec.loader.exec_module(bridge_module)
        arm = bridge_module.SimulatedArm()
        calls = []
        original = arm.set_joint_waypoints

        def record(waypoints, time_sec=None, speed_percent=None):
            calls.append([list(point) for point in waypoints])
            return original(
                waypoints,
                time_sec=time_sec,
                speed_percent=speed_percent,
            )

        arm.set_joint_waypoints = record
        bridge = bridge_module.RobotBridge()
        try:
            start = [0.1, 0.1, -0.1, 0.1, 0.1, 0.1]
            first = [0.2, 0.2, -0.2, 0.2, 0.2, 0.2]
            final = [0.3, 0.3, -0.3, 0.3, 0.3, 0.3]
            arm.joints = list(start)
            bridge.arm = arm
            bridge.connected = True
            bridge.state_ready = True
            bridge.last_valid_joints = list(start)
            bridge.enqueue_motion(
                {
                    "cmd": "move_joint_path",
                    "waypoints_rad": [first, final],
                    "time_sec": 0.2,
                    "request_id": "path-1",
                    "source": "test:continuous",
                }
            )
            deadline = time.monotonic() + 2.0
            while not calls and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                calls[0],
                [start, first, final],
            )
        finally:
            bridge.shutdown()

    def test_bridge_rejects_invalid_continuous_paths(self):
        bridge_path = ROOT / "web-control" / "server" / "startouch_bridge.py"
        bridge_spec = importlib.util.spec_from_file_location(
            "invalid_continuous_path_bridge",
            bridge_path,
        )
        assert bridge_spec and bridge_spec.loader
        bridge_module = importlib.util.module_from_spec(bridge_spec)
        bridge_spec.loader.exec_module(bridge_module)
        bridge = bridge_module.RobotBridge()
        messages = []
        original_emit = bridge_module.emit
        bridge_module.emit = lambda event, **payload: messages.append(
            {"type": event, **payload}
        )
        try:
            bridge.connected = True
            bridge.state_ready = True
            bridge.last_valid_joints = [0.1, 0.1, -0.1, 0.1, 0.1, 0.1]
            cases = [
                ([], "at least one"),
                ([[0.1, 0.1, -0.1]], "six values"),
                (
                    [[0.1, 0.1, float("nan"), 0.1, 0.1, 0.1]],
                    "non-finite",
                ),
                ([[0.0] * 6], "all-zero"),
                (
                    [[10.0, 0.1, -0.1, 0.1, 0.1, 0.1]],
                    "outside",
                ),
            ]
            for waypoints, expected in cases:
                with self.subTest(expected=expected):
                    messages.clear()
                    bridge.enqueue_motion(
                        {
                            "cmd": "move_joint_path",
                            "waypoints_rad": waypoints,
                            "source": "test:invalid",
                        }
                    )
                    self.assertTrue(bridge.motion_queue.empty())
                    self.assertTrue(
                        any(
                            expected in item.get("message", "")
                            for item in messages
                        ),
                        messages,
                    )
        finally:
            bridge_module.emit = original_emit
            bridge.shutdown()


if __name__ == "__main__":
    unittest.main()
