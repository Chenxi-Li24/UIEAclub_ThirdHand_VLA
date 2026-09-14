from __future__ import annotations

import math
from pathlib import Path
import queue
import threading

import numpy as np
import pytest

from robot_cartesian_adapter import CartesianPlanError, CartesianTranslationPlanner
from joint_tracking_compensator import (
    BoundedJointTrackingCompensator,
    JointTrackingCompensationError,
)
import startouch_bridge


PROJECT_ROOT = Path(__file__).parents[3]
URDF = PROJECT_ROOT / "web-control/web/models/startouch-v3/FastTouchV3.SLDASM.urdf"
JOINT_LIMITS = tuple(
    (math.radians(low), math.radians(high))
    for low, high in [
        (-162, 162), (-12, 201), (-183, 0),
        (-98, 98), (-98, 98), (-164, 164),
    ]
)
HOME_JOINTS = np.radians(
    [6.4368684926385455, -11.813675450835769, -0.5792088796431968,
     32.99304920080786, -5.6063048161690565, -4.491600934591583]
)
HOME_POSITION = np.array(
    [0.26783482212847776, 0.010668622392713049, 0.08034337217225807]
)
HOME_EULER = np.array(
    [-0.11509721885862755, 0.35774335307079097, 0.007859118118603986]
)


def planner() -> CartesianTranslationPlanner:
    return CartesianTranslationPlanner.from_urdf(
        URDF,
        tool_xyz_m=(0.17334, 0.0, 0.0),
        joint_limits_rad=JOINT_LIMITS,
        max_translation_m=0.020,
        max_joint_delta_rad=math.radians(15),
    )


def test_fk_matches_the_live_catalogued_table_center_pose() -> None:
    transform = planner().forward_kinematics(HOME_JOINTS)

    assert transform[:3, 3] == pytest.approx(HOME_POSITION, abs=1e-9)
    assert planner().euler_xyz(transform[:3, :3]) == pytest.approx(HOME_EULER, abs=1e-9)


def test_plans_the_observed_twenty_millimetre_refinement_as_a_bounded_joint_path() -> None:
    delta = np.array([-0.0011718, -0.0183757, -0.0078078])
    delta *= 0.020 / np.linalg.norm(delta)
    result = planner().plan_translation(
        current_joints_rad=HOME_JOINTS,
        measured_position_m=HOME_POSITION,
        measured_euler_rad=HOME_EULER,
        target_position_m=HOME_POSITION + delta,
        target_euler_rad=HOME_EULER,
    )

    assert result.target_position_error_m <= 0.001
    assert result.target_orientation_error_rad <= 0.025
    assert result.max_tcp_displacement_m <= np.linalg.norm(delta) + 0.001
    assert result.max_transverse_error_m <= 0.002
    assert result.max_joint_delta_rad <= math.radians(15)
    assert len(result.target_joints_rad) == 6


def test_plans_bounded_translation_and_base_frame_optical_rotation() -> None:
    current_joints = np.radians([-6.57, -11.88, -0.47, 33.04, 6.46, -9.04])
    current_pose = planner().forward_kinematics(current_joints)
    delta = np.array([-0.00236181, -0.01616176, -0.01154208])
    delta *= 0.020 / np.linalg.norm(delta)
    rotation_delta = np.array([-0.02122418, 0.05122596, -0.06738598])

    result = planner().plan_pose_delta(
        current_joints_rad=current_joints,
        measured_position_m=current_pose[:3, 3],
        measured_euler_rad=planner().euler_xyz(current_pose[:3, :3]),
        target_position_m=current_pose[:3, 3] + delta,
        rotation_delta_base_rad=rotation_delta,
    )

    assert result.target_position_error_m <= 0.001
    assert result.target_orientation_error_rad <= 0.025
    assert result.max_tcp_displacement_m <= 0.021
    assert result.max_transverse_error_m <= 0.002
    assert result.max_joint_delta_rad <= math.radians(15)
    assert np.linalg.norm(result.target_rotation_delta_rad) == pytest.approx(
        math.radians(5), abs=1e-8
    )


def test_plans_rotation_only_without_lowering_the_tcp() -> None:
    current_pose = planner().forward_kinematics(HOME_JOINTS)
    rotation_delta = np.array([0.0, math.radians(1.0), 0.0])

    result = planner().plan_pose_delta(
        current_joints_rad=HOME_JOINTS,
        measured_position_m=current_pose[:3, 3],
        measured_euler_rad=planner().euler_xyz(current_pose[:3, :3]),
        target_position_m=current_pose[:3, 3],
        rotation_delta_base_rad=rotation_delta,
    )

    assert result.target_position_error_m <= 0.001
    assert result.target_orientation_error_rad <= 0.025
    assert result.max_tcp_displacement_m <= 0.002
    assert result.max_joint_delta_rad <= math.radians(15)


def test_replans_from_measured_undertravel_to_the_same_absolute_pose() -> None:
    initial_delta = np.array([-0.001, -0.009, -0.004])
    initial_delta *= 0.010 / np.linalg.norm(initial_delta)
    initial_rotation = np.array([0.0, math.radians(2.45), 0.0])
    first = planner().plan_pose_delta(
        current_joints_rad=HOME_JOINTS,
        measured_position_m=HOME_POSITION,
        measured_euler_rad=HOME_EULER,
        target_position_m=HOME_POSITION + initial_delta,
        rotation_delta_base_rad=initial_rotation,
    )
    undertravel_joints = HOME_JOINTS + 0.7 * (
        np.asarray(first.target_joints_rad) - HOME_JOINTS
    )
    undertravel_pose = planner().forward_kinematics(undertravel_joints)

    correction = planner().plan_pose_target(
        current_joints_rad=undertravel_joints,
        measured_position_m=undertravel_pose[:3, 3],
        measured_euler_rad=planner().euler_xyz(undertravel_pose[:3, :3]),
        target_position_m=HOME_POSITION + initial_delta,
        target_euler_rad=first.target_euler_rad,
    )

    assert correction.target_position_error_m <= 0.001
    assert correction.target_orientation_error_rad <= 0.025
    assert correction.max_tcp_displacement_m <= 0.011
    assert correction.max_joint_delta_rad <= math.radians(15)


def test_rejects_model_pose_mismatch_and_oversized_translation() -> None:
    with pytest.raises(CartesianPlanError, match="measured pose"):
        planner().plan_translation(
            current_joints_rad=HOME_JOINTS,
            measured_position_m=HOME_POSITION + np.array([0.01, 0.0, 0.0]),
            measured_euler_rad=HOME_EULER,
            target_position_m=HOME_POSITION,
            target_euler_rad=HOME_EULER,
        )
    with pytest.raises(CartesianPlanError, match="translation"):
        planner().plan_translation(
            current_joints_rad=HOME_JOINTS,
            measured_position_m=HOME_POSITION,
            measured_euler_rad=HOME_EULER,
            target_position_m=HOME_POSITION + np.array([0.021, 0.0, 0.0]),
            target_euler_rad=HOME_EULER,
        )


def test_real_active_view_move_uses_validated_adapter_but_keeps_move_l_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeArm:
        def get_ee_pose_euler(self):
            return HOME_POSITION.copy(), HOME_EULER.copy()

    bridge = object.__new__(startouch_bridge.RobotBridge)
    bridge.arm_lock = threading.RLock()
    bridge.connected = True
    bridge.state_ready = True
    bridge.motion_active = False
    bridge.motion_queue = queue.Queue(maxsize=1)
    bridge.arm = FakeArm()
    bridge.last_valid_joints = HOME_JOINTS.tolist()
    bridge.cartesian_planner = planner()
    bridge.cartesian_planner_error = None
    bridge._emit_joint_log = lambda *args, **kwargs: None
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(startouch_bridge, "SIMULATE", False)
    monkeypatch.setattr(
        startouch_bridge,
        "emit",
        lambda event_type, **payload: events.append((event_type, payload)),
    )
    delta = np.array([-0.0011718, -0.0183757, -0.0078078])
    delta *= 0.020 / np.linalg.norm(delta)

    bridge.move_linear(
        {
            "cmd": "move_l",
            "position": (HOME_POSITION + delta).tolist(),
            "euler": HOME_EULER.tolist(),
            "time_sec": 2.0,
            "request_id": "request-1",
            "source": "active_view:refine",
        }
    )

    queued = bridge.motion_queue.get_nowait()
    assert queued["_active_view_joint_plan"] is True
    assert queued["command"] == "move_l"
    assert max(abs(np.asarray(queued["joints_rad"]) - HOME_JOINTS)) <= math.radians(15)
    assert queued["time_sec"] >= 4.0
    assert ("command_accepted", {
        "command": "move_l", "request_id": "request-1", "source": "active_view:refine",
    }) in events


def test_active_view_executes_validated_joint_target_with_hold_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[float], float]] = []

    class FakeArm:
        def set_joint(self, target, tf):
            calls.append((list(target), float(tf)))

        def set_joint_waypoints(self, *args, **kwargs):
            raise AssertionError("active-view target must use the hold backend")

    bridge = object.__new__(startouch_bridge.RobotBridge)
    bridge.stop_requested = threading.Event()
    monkeypatch.setattr(startouch_bridge, "SIMULATE", True)
    target = [0.1, -0.2, -0.3, 0.4, -0.5, 0.6]

    duration = bridge._execute_active_view_joint_target(
        FakeArm(),
        {"joints_rad": target, "time_sec": 4.0},
    )

    assert duration == pytest.approx(4.0)
    assert calls == [(target, 4.0)]


def test_active_view_replans_undertravel_to_the_same_validated_pose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kinematics = planner()
    delta = np.array([-0.001, -0.009, -0.004])
    delta *= 0.010 / np.linalg.norm(delta)
    first = kinematics.plan_pose_delta(
        current_joints_rad=HOME_JOINTS,
        measured_position_m=HOME_POSITION,
        measured_euler_rad=HOME_EULER,
        target_position_m=HOME_POSITION + delta,
        rotation_delta_base_rad=[0.0, math.radians(2.45), 0.0],
    )

    class UndertravelArm:
        def __init__(self):
            target = np.asarray(first.target_joints_rad)
            self.static_error = np.radians([0.1, 0.1, 0.55, 0.75, 0.1, 0.2])
            self.joints = target - self.static_error
            self.calls: list[tuple[list[float], float]] = []

        def get_joint_positions(self):
            return self.joints.tolist()

        def get_ee_pose_euler(self):
            pose = kinematics.forward_kinematics(self.joints)
            return pose[:3, 3], kinematics.euler_xyz(pose[:3, :3])

        def set_joint(self, target, tf):
            self.calls.append((list(target), float(tf)))
            target = np.asarray(target)
            self.joints = target - self.static_error

    bridge = object.__new__(startouch_bridge.RobotBridge)
    bridge.stop_requested = threading.Event()
    bridge.cartesian_planner = kinematics
    bridge.joint_tracking_compensator = BoundedJointTrackingCompensator()
    arm = UndertravelArm()
    monkeypatch.setattr(startouch_bridge, "SIMULATE", True)
    command = {
        "joints_rad": list(first.target_joints_rad),
        "_move_l_pos": (HOME_POSITION + delta).tolist(),
        "_move_l_euler": list(first.target_euler_rad),
        "_move_l_position_tolerance_m": 0.003,
        "_move_l_orientation_tolerance_rad": 0.08,
        "_active_view_correction_translation_limit_m": 0.011,
        "_active_view_correction_rotation_limit_rad": math.radians(5),
    }

    result = bridge._correct_active_view_endpoint(arm, command)

    assert result["position_error_m"] <= 0.003
    assert result["orientation_error_rad"] <= 0.08
    assert 1 <= result["correction_count"] <= 2
    assert len(arm.calls) == result["correction_count"]


def test_joint_tracking_compensation_accumulates_bounded_measured_error() -> None:
    compensator = BoundedJointTrackingCompensator(
        gain=0.75,
        max_total_bias_rad=math.radians(1.5),
        max_increment_rad=math.radians(1.0),
    )
    desired = np.radians([4.7, -8.2, -1.4, 31.6, -6.2, -4.8])
    actual = desired - np.radians([0.1, 0.1, 0.55, 0.75, 0.1, 0.2])

    correction = compensator.next_target(
        desired_joints_rad=desired,
        previous_command_rad=desired,
        actual_joints_rad=actual,
        joint_limits_rad=JOINT_LIMITS,
    )

    expected = desired + 0.75 * (desired - actual)
    assert correction.target_joints_rad == pytest.approx(expected)
    assert correction.max_increment_rad <= math.radians(1.0)
    assert correction.max_total_bias_rad <= math.radians(1.5)


def test_joint_tracking_compensation_rejects_unbounded_bias() -> None:
    compensator = BoundedJointTrackingCompensator(
        gain=0.75,
        max_total_bias_rad=math.radians(1.5),
        max_increment_rad=math.radians(1.0),
    )
    desired = HOME_JOINTS.copy()
    actual = desired.copy()
    actual[3] -= math.radians(2.0)

    with pytest.raises(JointTrackingCompensationError, match="increment"):
        compensator.next_target(
            desired_joints_rad=desired,
            previous_command_rad=desired,
            actual_joints_rad=actual,
            joint_limits_rad=JOINT_LIMITS,
        )
