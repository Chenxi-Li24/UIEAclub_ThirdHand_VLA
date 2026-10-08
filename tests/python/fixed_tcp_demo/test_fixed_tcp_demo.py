import csv
import math
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEMO_ROOT = ROOT / "apps" / "fixed_tcp_demo"
for path in (str(DEMO_ROOT), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from demo import DemoConfig, FixedTcpDemo, PlannedPoint
from logger import CsvPoseLogger
from safety import SafetyError, assert_known_collision_zones, euler_to_quaternion_wxyz
from trajectory import FixedTcpTrajectory, RCMConeOrbitTrajectory, euler_to_matrix


class FakeArm:
    def __init__(self, ik_ok=True):
        self.pos = [0.35, 0.0, 0.25]
        self.euler = [0.1, -0.2, 0.3]
        self.joints = [0.0, 0.1, -0.2, 0.0, 0.0, 0.0]
        self.commands = []
        self.ik_positions = []
        self.cleaned = False
        self.ik_ok = ik_ok

    def get_ee_pose_euler(self):
        return list(self.pos), list(self.euler)

    def get_joint_positions(self):
        return list(self.joints)

    def solve_ik(self, pos, quat, q_seed=None):
        self.ik_positions.append(list(pos))
        assert len(quat) == 4
        assert len(q_seed) == 6
        if not self.ik_ok:
            return list(self.joints), False
        base = list(q_seed)
        target = [
            base[0],
            base[1],
            base[2],
            base[3] + 0.01,
            base[4] + 0.01,
            base[5] + 0.01,
        ]
        return target, True

    def set_joint_waypoints(self, waypoints, time_sec=None, speed_percent=None):
        self.commands.append((waypoints, time_sec, speed_percent))
        self.joints = list(waypoints[-1])
        return time_sec

    def cleanup(self):
        self.cleaned = True


class DriftingArm(FakeArm):
    def __init__(self):
        super().__init__(ik_ok=True)
        self.command_count = 0

    def get_ee_pose_euler(self):
        drift = 0.05 if self.command_count else 0.0
        return [self.pos[0] + drift, self.pos[1], self.pos[2]], list(self.euler)

    def set_joint_waypoints(self, waypoints, time_sec=None, speed_percent=None):
        self.command_count += 1
        return super().set_joint_waypoints(waypoints, time_sec, speed_percent)


class DelayedStateArm(FakeArm):
    def __init__(self):
        super().__init__(ik_ok=True)
        self.position_reads = 0

    def get_joint_positions(self):
        self.position_reads += 1
        if self.position_reads < 3:
            raise RuntimeError("joint state is not available")
        return list(self.joints)


class RetryPlanningDemo(FixedTcpDemo):
    def __init__(self, *args, fail_above_deg=30.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_above_deg = fail_above_deg
        self.tried_cone_angles = []

    def plan_full_trajectory(self):
        assert self.trajectory is not None
        cone_deg = math.degrees(self.trajectory.cone_angle_rad)
        self.tried_cone_angles.append(cone_deg)
        if cone_deg > self.fail_above_deg:
            raise SafetyError("synthetic wrist risk")
        return [PlannedPoint(0.0, self.center_rpy or [0.0, 0.0, 0.0], self.last_target_joints or [0.0] * 6)]


def test_cancelled_demo_does_not_send_return_to_zero(tmp_path):
    arm = FakeArm()
    demo = FixedTcpDemo(arm, config=DemoConfig(execute=True, dry_run=False), log_dir=tmp_path)
    demo.stop_requested = threading.Event()
    demo.initialize = lambda: None
    demo.plan_full_trajectory_with_auto_amplitude = lambda: []
    demo._execute_planned_trajectory = lambda plan: demo.stop_requested.set()
    try:
        with pytest.raises(SafetyError, match="cancel"):
            demo.run_forever()
        assert arm.commands == []
    finally:
        demo.logger.close()


def test_every_demo_stage_uses_the_configured_bounded_speed(tmp_path):
    arm = FakeArm()
    arm.joints[0] = math.radians(150)
    demo = FixedTcpDemo(arm, config=DemoConfig(
        execute=True, dry_run=False, execute_speed_percent=0.02,
        use_current_tcp_xyz=True, duration_sec=1, control_hz=10,
    ), log_dir=tmp_path)
    try:
        demo.initialize()
        demo.run_one_step(0)
        demo._execute_planned_trajectory([PlannedPoint(0, demo.center_rpy, arm.joints)])
        demo._return_to_home()
        assert len(arm.commands) == 5
        assert all(time_sec is None and speed == 0.02 for _, time_sec, speed in arm.commands)
    finally:
        demo.logger.close()


def test_trajectory_stays_inside_configured_orientation_amplitude():
    center = [0.4, -0.3, 0.2]
    traj = FixedTcpTrajectory(
        center,
        max_roll_rad=math.radians(5),
        max_pitch_rad=math.radians(5),
        max_yaw_rad=math.radians(5),
        period_sec=8.0,
    )

    samples = [traj.sample(i / 20.0) for i in range(160)]

    for sample in samples:
        assert max(abs(a - b) for a, b in zip(sample, center)) <= math.radians(5) + 1e-9
    assert any(abs(sample[0] - center[0]) > math.radians(1.5) for sample in samples)
    assert any(sample[1] - center[1] > math.radians(4.5) for sample in samples)
    assert any(sample[1] - center[1] < -math.radians(4.5) for sample in samples)
    assert any(sample[2] - center[2] > math.radians(4.5) for sample in samples)
    assert any(sample[2] - center[2] < -math.radians(4.5) for sample in samples)


def test_rcm_cone_orbit_keeps_tool_axis_on_constant_cone():
    center = [0.0, 0.0, 0.0]
    cone_angle = math.radians(20.0)
    traj = RCMConeOrbitTrajectory(
        center,
        cone_angle_rad=cone_angle,
        period_sec=8.0,
        ramp_sec=0.0,
        cone_pulse_fraction=0.0,
        phase_wobble_rad=0.0,
    )

    samples = [traj.sample(i * 8.0 / 16) for i in range(16)]
    axes = [[row[0] for row in euler_to_matrix(sample)] for sample in samples]
    center_axis = [1.0, 0.0, 0.0]
    cone_angles = [
        math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(axis, center_axis)))))
        for axis in axes
    ]

    assert max(abs(angle - cone_angle) for angle in cone_angles) < math.radians(0.1)
    assert min(axis[1] for axis in axes) < -0.30
    assert max(axis[1] for axis in axes) > 0.30
    assert min(axis[2] for axis in axes) < -0.30
    assert max(axis[2] for axis in axes) > 0.30


def test_rcm_cone_orbit_starts_and_ends_at_center_when_ramped():
    center = [0.0, 0.0, 0.0]
    cone_angle = math.radians(30.0)
    traj = RCMConeOrbitTrajectory(
        center,
        cone_angle_rad=cone_angle,
        period_sec=8.0,
        duration_sec=20.0,
        ramp_sec=4.0,
        cone_pulse_fraction=0.0,
        phase_wobble_rad=0.0,
    )

    start_axis = [row[0] for row in euler_to_matrix(traj.sample(0.0))]
    full_axis = [row[0] for row in euler_to_matrix(traj.sample(8.0))]
    end_axis = [row[0] for row in euler_to_matrix(traj.sample(20.0))]
    center_axis = [1.0, 0.0, 0.0]

    def axis_angle(axis):
        return math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(axis, center_axis)))))

    assert axis_angle(start_axis) < math.radians(0.1)
    assert abs(axis_angle(full_axis) - cone_angle) < math.radians(0.1)
    assert axis_angle(end_axis) < math.radians(0.1)


def test_rcm_cone_orbit_can_pulse_radius_without_exceeding_limit():
    center = [0.0, 0.0, 0.0]
    cone_angle = math.radians(42.0)
    traj = RCMConeOrbitTrajectory(
        center,
        cone_angle_rad=cone_angle,
        period_sec=3.0,
        ramp_sec=0.0,
        cone_pulse_fraction=0.25,
        phase_wobble_rad=0.20,
    )

    samples = [traj.sample(i * 3.0 / 240) for i in range(240)]
    axes = [[row[0] for row in euler_to_matrix(sample)] for sample in samples]
    center_axis = [1.0, 0.0, 0.0]
    cone_angles = [
        math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(axis, center_axis)))))
        for axis in axes
    ]

    assert max(cone_angles) <= cone_angle + math.radians(0.1)
    assert max(cone_angles) > math.radians(41.0)
    assert min(cone_angles) < math.radians(33.0)
    assert min(axis[1] for axis in axes) < -0.55
    assert max(axis[1] for axis in axes) > 0.55
    assert min(axis[2] for axis in axes) < -0.55
    assert max(axis[2] for axis in axes) > 0.55


def test_rcm_lissajous_envelope_visits_multiple_directions_smoothly():
    center = [0.0, 0.0, 0.0]
    cone_angle = math.radians(38.0)
    traj = RCMConeOrbitTrajectory(
        center,
        cone_angle_rad=cone_angle,
        period_sec=6.0,
        ramp_sec=0.0,
        path_style="lissajous",
        cone_pulse_fraction=0.0,
        phase_wobble_rad=0.0,
    )

    samples = [traj.sample(i * 6.0 / 360) for i in range(361)]
    axes = [[row[0] for row in euler_to_matrix(sample)] for sample in samples]
    center_axis = [1.0, 0.0, 0.0]
    cone_angles = [
        math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(axis, center_axis)))))
        for axis in axes
    ]
    axis_steps = [
        math.sqrt(sum((after[i] - before[i]) ** 2 for i in range(3)))
        for before, after in zip(axes, axes[1:])
    ]

    assert max(cone_angles) <= cone_angle + math.radians(0.1)
    assert min(axis[1] for axis in axes) < -0.45
    assert max(axis[1] for axis in axes) > 0.45
    assert min(axis[2] for axis in axes) < -0.45
    assert max(axis[2] for axis in axes) > 0.45
    assert max(axis_steps) < 0.04


def test_rcm_cardinal_cross_moves_between_up_down_left_right_smoothly():
    center = [0.0, 0.0, 0.0]
    cone_angle = math.radians(30.0)
    traj = RCMConeOrbitTrajectory(
        center,
        cone_angle_rad=cone_angle,
        period_sec=8.0,
        ramp_sec=0.0,
        path_style="cardinal_cross",
        cone_pulse_fraction=0.0,
        phase_wobble_rad=0.0,
    )

    samples = [traj.sample(i * 8.0 / 480) for i in range(481)]
    axes = [[row[0] for row in euler_to_matrix(sample)] for sample in samples]
    axis_steps = [
        math.sqrt(sum((after[i] - before[i]) ** 2 for i in range(3)))
        for before, after in zip(axes, axes[1:])
    ]

    assert max(axis[1] for axis in axes) > 0.49
    assert min(axis[1] for axis in axes) < -0.49
    assert max(axis[2] for axis in axes) > 0.49
    assert min(axis[2] for axis in axes) < -0.49
    assert max(axis_steps) < 0.035


def test_rcm_nod_shake_and_spiral_breathe_are_smooth_direction_patterns():
    center = [0.0, 0.0, 0.0]
    nod = RCMConeOrbitTrajectory(
        center,
        cone_angle_rad=math.radians(28.0),
        period_sec=6.0,
        ramp_sec=0.0,
        path_style="nod_shake",
        cone_pulse_fraction=0.0,
        phase_wobble_rad=0.0,
    )
    spiral = RCMConeOrbitTrajectory(
        center,
        cone_angle_rad=math.radians(32.0),
        period_sec=6.0,
        ramp_sec=0.0,
        path_style="spiral_breathe",
        cone_pulse_fraction=0.0,
        phase_wobble_rad=0.0,
    )

    nod_axes = [[row[0] for row in euler_to_matrix(nod.sample(i * 6.0 / 480))] for i in range(481)]
    spiral_axes = [[row[0] for row in euler_to_matrix(spiral.sample(i * 6.0 / 480))] for i in range(481)]
    nod_steps = [
        math.sqrt(sum((after[i] - before[i]) ** 2 for i in range(3)))
        for before, after in zip(nod_axes, nod_axes[1:])
    ]
    spiral_steps = [
        math.sqrt(sum((after[i] - before[i]) ** 2 for i in range(3)))
        for before, after in zip(spiral_axes, spiral_axes[1:])
    ]
    spiral_radii = [math.hypot(axis[1], axis[2]) for axis in spiral_axes]

    assert max(axis[1] for axis in nod_axes) > 0.46
    assert min(axis[1] for axis in nod_axes) < -0.46
    assert max(axis[2] for axis in nod_axes) > 0.46
    assert min(axis[2] for axis in nod_axes) < -0.46
    assert max(nod_steps) < 0.04
    assert max(spiral_radii) - min(spiral_radii) > 0.30
    assert max(spiral_steps) < 0.04


def test_rcm_irregular_shell_covers_an_asymmetric_large_envelope_smoothly():
    center = [0.0, 0.0, 0.0]
    traj = RCMConeOrbitTrajectory(
        center,
        cone_angle_rad=math.radians(35.0),
        period_sec=8.0,
        ramp_sec=0.0,
        path_style="irregular_shell",
        cone_pulse_fraction=0.0,
        phase_wobble_rad=0.0,
    )

    samples = [traj.sample(i * 8.0 / 640) for i in range(641)]
    axes = [[row[0] for row in euler_to_matrix(sample)] for sample in samples]
    axis_steps = [
        math.sqrt(sum((after[i] - before[i]) ** 2 for i in range(3)))
        for before, after in zip(axes, axes[1:])
    ]
    radii = [math.hypot(axis[1], axis[2]) for axis in axes]

    assert max(axis[1] for axis in axes) > 0.48
    assert min(axis[1] for axis in axes) < -0.44
    assert max(axis[2] for axis in axes) > 0.50
    assert min(axis[2] for axis in axes) < -0.50
    assert max(radii) - min(radii) > 0.18
    assert max(axis_steps) < 0.035


def test_euler_to_quaternion_wxyz_returns_unit_quaternion():
    quat = euler_to_quaternion_wxyz([0.2, -0.1, 0.4])
    assert len(quat) == 4
    assert math.isclose(math.sqrt(sum(value * value for value in quat)), 1.0)


def test_demo_step_checks_ik_before_sending_motion(tmp_path):
    arm = FakeArm(ik_ok=True)
    config = DemoConfig(dry_run=False, execute=True, control_hz=20.0, start_from_zero=False)
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)
    demo.initialize()
    arm.ik_ok = False

    with pytest.raises(SafetyError, match="IK failed"):
        demo.run_one_step(elapsed_sec=0.0)

    assert len(arm.commands) == 1


def test_demo_dry_run_logs_without_sending_motion(tmp_path):
    arm = FakeArm(ik_ok=True)
    config = DemoConfig(
        dry_run=True,
        execute=False,
        control_hz=20.0,
        start_from_zero=False,
        use_current_tcp_xyz=True,
    )
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)
    demo.initialize()
    demo.run_one_step(elapsed_sec=0.0)

    assert arm.commands == []
    assert demo.log_path is not None
    rows = list(csv.DictReader(demo.log_path.open()))
    assert rows
    assert "error_mm" in rows[0]
    assert "q6" in rows[0]


def test_demo_stops_when_tcp_error_exceeds_limit_after_motion(tmp_path):
    arm = DriftingArm()
    config = DemoConfig(
        dry_run=False,
        execute=True,
        start_from_zero=False,
        use_current_tcp_xyz=True,
        max_position_error_mm=20.0,
    )
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)
    demo.initialize()

    with pytest.raises(SafetyError, match="TCP position error"):
        demo.run_one_step(elapsed_sec=0.0)


def test_demo_moves_to_zero_before_locking_tcp(tmp_path):
    arm = FakeArm(ik_ok=True)
    arm.joints = [0.2, 0.3, -0.4, 0.1, 0.0, 0.0]
    config = DemoConfig(dry_run=False, execute=True, start_from_zero=True, zero_time_sec=3.0)
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)

    demo.initialize()

    assert arm.commands[0] == ([[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]], None, 0.05)
    assert len(arm.commands) == 2
    assert demo.last_target_joints != [0.0] * 6


def test_demo_moves_to_center_pose_after_zero_for_configured_point(tmp_path):
    arm = FakeArm(ik_ok=True)
    config = DemoConfig(
        dry_run=False,
        execute=True,
        start_from_zero=True,
        fixed_xyz=[0.48, 0.0, 0.36],
        center_move_time_sec=4.0,
    )
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)

    demo.initialize()

    assert len(arm.commands) == 2
    assert arm.commands[0][0] == [[0.0] * 6]
    assert arm.commands[1][1:] == (None, 0.05)


def test_demo_waits_for_joint_state_before_zero_move(tmp_path):
    arm = DelayedStateArm()
    config = DemoConfig(
        dry_run=False,
        execute=True,
        start_from_zero=True,
        startup_state_timeout_sec=1.0,
        startup_state_poll_sec=0.001,
    )
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)

    demo.initialize()

    assert arm.position_reads >= 3
    assert arm.commands[0][0] == [[0.0] * 6]


def test_demo_stops_after_configured_duration(tmp_path):
    arm = FakeArm(ik_ok=True)
    config = DemoConfig(dry_run=True, execute=False, start_from_zero=False, duration_sec=1.0)
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)
    demo.initialize()

    assert demo.should_continue(0.99) is True
    assert demo.should_continue(1.0) is False


def test_demo_auto_reduces_cone_angle_when_precheck_rejects_risky_pose(tmp_path):
    arm = FakeArm(ik_ok=True)
    config = DemoConfig(
        dry_run=True,
        execute=False,
        start_from_zero=False,
        max_cone_deg=35.0,
        allow_max_cone_deg=40.0,
        min_auto_cone_deg=20.0,
    )
    demo = RetryPlanningDemo(arm, config=config, log_dir=tmp_path, fail_above_deg=30.0)
    demo.initialize()

    plan = demo.plan_full_trajectory_with_auto_amplitude()

    assert len(plan) == 1
    assert demo.tried_cone_angles == pytest.approx([35.0, 32.0, 30.0])
    assert math.isclose(math.degrees(demo.trajectory.cone_angle_rad), 30.0)


def test_demo_builds_multi_motion_sequence_by_default(tmp_path):
    arm = FakeArm(ik_ok=True)
    config = DemoConfig(dry_run=True, execute=False, start_from_zero=False, duration_sec=60.0)
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)
    demo.initialize()

    names = [item.profile.name for item in demo.trajectory_sequence]
    styles = [item.profile.path_style for item in demo.trajectory_sequence]

    assert names == [
        "cone_clockwise",
        "cardinal_cross",
        "irregular_shell",
        "flower_envelope",
        "nod_shake",
        "spiral_breathe",
        "cone_counterclockwise",
        "wide_flower_finish",
    ]
    assert styles == [
        "orbit",
        "cardinal_cross",
        "irregular_shell",
        "lissajous",
        "nod_shake",
        "spiral_breathe",
        "orbit",
        "lissajous",
    ]
    assert demo.trajectory_sequence[0].profile.phase_direction == 1.0
    assert demo.trajectory_sequence[6].profile.phase_direction == -1.0


def test_demo_executes_one_prechecked_smooth_trajectory_then_returns_home(tmp_path):
    arm = FakeArm(ik_ok=True)
    config = DemoConfig(
        dry_run=False,
        execute=True,
        start_from_zero=False,
        use_current_tcp_xyz=True,
        duration_sec=1.0,
        control_hz=10.0,
        center_move_time_sec=2.0,
        return_home_time_sec=3.0,
    )
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)

    demo.run_forever()

    assert len(arm.commands) == 3
    assert arm.commands[0][1:] == (None, 0.05)
    smooth_waypoints, smooth_time, smooth_speed = arm.commands[1]
    assert smooth_time is None
    assert smooth_speed == 0.05
    assert len(smooth_waypoints) == 11
    assert arm.commands[2][0][-1] == [0.0] * 6
    assert arm.commands[2][1:] == (None, 0.05)


def test_known_collision_zones_reject_sdk_documented_risky_postures():
    with pytest.raises(SafetyError, match="wrist"):
        assert_known_collision_zones([0.0, 0.8, -1.2, 0.3, math.radians(82), 0.0])
    with pytest.raises(SafetyError, match="J3/J4"):
        assert_known_collision_zones([0.0, 0.0, -0.7685, 1.5153, 0.0, 0.0])
    with pytest.raises(SafetyError, match="elbow"):
        assert_known_collision_zones([0.0, 1.45, -2.912226, -0.267559, 0.0, 0.0])


def test_demo_uses_configured_fixed_xyz_by_default(tmp_path):
    arm = FakeArm(ik_ok=True)
    config = DemoConfig(
        dry_run=True,
        execute=False,
        fixed_xyz=[0.30084, 0.0, 0.17605],
        use_current_tcp_xyz=False,
        start_from_zero=False,
    )
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)
    demo.initialize()

    assert demo.fixed_xyz == [0.30084, 0.0, 0.17605]


def test_demo_default_fixed_xyz_is_sdk_screened_show_point(tmp_path):
    arm = FakeArm(ik_ok=True)
    config = DemoConfig(dry_run=True, execute=False, start_from_zero=False)
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)
    demo.initialize()

    assert demo.fixed_xyz == [0.48, 0.0, 0.36]


def test_dramatic_trajectory_has_exhibition_wrist_bias_on_visible_side():
    center = [0.0, 0.0, 0.0]
    traj = FixedTcpTrajectory(
        center,
        max_roll_rad=math.radians(35),
        max_pitch_rad=math.radians(35),
        max_yaw_rad=math.radians(35),
        period_sec=8.0,
    )

    visible_side = traj.sample(2.0)
    samples = [traj.sample(i * 8.0 / 160) for i in range(160)]

    assert math.degrees(visible_side[0]) > 13.0
    assert math.degrees(visible_side[2]) > 34.0
    assert max(math.degrees(abs(sample[2])) for sample in samples) > 34.0


def test_dramatic_trajectory_visits_all_sides_of_the_fixed_point():
    center = [0.0, 0.0, 0.0]
    traj = FixedTcpTrajectory(
        center,
        max_roll_rad=math.radians(35),
        max_pitch_rad=math.radians(35),
        max_yaw_rad=math.radians(35),
        period_sec=8.0,
    )

    samples = [traj.sample(i * 8.0 / 240) for i in range(240)]
    mins = [min(math.degrees(sample[axis]) for sample in samples) for axis in range(3)]
    maxs = [max(math.degrees(sample[axis]) for sample in samples) for axis in range(3)]

    assert mins[0] < -13.0
    assert maxs[0] > 13.0
    assert mins[1] < -34.0
    assert maxs[1] > 34.0
    assert mins[2] < -34.0
    assert maxs[2] > 34.0


def test_dramatic_trajectory_wraps_the_tip_smoothly_from_all_directions():
    traj = FixedTcpTrajectory(
        [0.0, 0.0, 0.0],
        max_roll_rad=math.radians(35),
        max_pitch_rad=math.radians(35),
        max_yaw_rad=math.radians(35),
        period_sec=12.0,
    )

    samples = [traj.sample(i * 12.0 / 360) for i in range(361)]
    degrees = [[math.degrees(value) for value in sample] for sample in samples]
    max_step = max(
        max(abs(a - b) for a, b in zip(after, before))
        for before, after in zip(degrees, degrees[1:])
    )

    assert max_step < 1.5
    assert min(sample[0] for sample in degrees) < -13.0
    assert max(sample[0] for sample in degrees) > 13.0
    for axis in (1, 2):
        assert min(sample[axis] for sample in degrees) < -34.0
        assert max(sample[axis] for sample in degrees) > 34.0


def test_demo_can_still_lock_current_tcp_when_requested(tmp_path):
    arm = FakeArm(ik_ok=True)
    config = DemoConfig(dry_run=True, execute=False, use_current_tcp_xyz=True, start_from_zero=False)
    demo = FixedTcpDemo(arm, config=config, log_dir=tmp_path)
    demo.initialize()

    assert demo.fixed_xyz == arm.pos


def test_csv_logger_writes_required_fields(tmp_path):
    logger = CsvPoseLogger(tmp_path)
    logger.write(
        timestamp=1.25,
        target_xyz=[1, 2, 3],
        actual_xyz=[1, 2, 3.001],
        error_mm=1.0,
        target_rpy=[0.1, 0.2, 0.3],
        actual_rpy=[0.1, 0.2, 0.3],
        joints=[0, 1, 2, 3, 4, 5],
        loop_hz=99.0,
        ik_status="ok",
    )
    logger.close()

    row = next(csv.DictReader(logger.path.open()))
    assert row["target_x"] == "1"
    assert row["actual_z"] == "3.001"
    assert row["ik_status"] == "ok"
