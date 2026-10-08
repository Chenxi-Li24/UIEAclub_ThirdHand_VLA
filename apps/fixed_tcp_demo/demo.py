from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from logger import CsvPoseLogger
from safety import (
    SafetyError,
    assert_joint_acceleration,
    assert_joint_limits,
    assert_known_collision_zones,
    assert_orientation_delta,
    assert_step_size,
    assert_workspace_position,
    euler_to_quaternion_wxyz,
    finite_vector,
)
from trajectory import RCMConeOrbitTrajectory


@dataclass(frozen=True)
class DemoConfig:
    dry_run: bool = True
    execute: bool = False
    control_hz: float = 50.0
    command_time_sec: float = 0.08
    print_interval_sec: float = 0.5
    fixed_xyz: list[float] | None = None
    use_current_tcp_xyz: bool = False
    start_from_zero: bool = True
    zero_time_sec: float = 3.0
    center_move_time_sec: float = 6.0
    return_home_time_sec: float = 4.0
    duration_sec: float = 60.0
    max_cone_deg: float = 50.0
    allow_max_cone_deg: float = 50.0
    min_auto_cone_deg: float = 25.0
    max_joint_step_deg: float = 3.0
    max_joint_accel_step_deg: float = 2.0
    max_position_error_mm: float = 25.0
    period_sec: float = 6.0
    ramp_sec: float = 3.0
    transition_sec: float = 1.5
    cone_pulse_fraction: float = 0.0
    phase_wobble_rad: float = 0.0
    path_style: str = "lissajous"
    execute_speed_percent: float = 0.05
    startup_state_timeout_sec: float = 5.0
    startup_state_poll_sec: float = 0.1


@dataclass(frozen=True)
class PlannedPoint:
    elapsed_sec: float
    target_rpy: list[float]
    joints: list[float]


@dataclass(frozen=True)
class MotionProfile:
    name: str
    path_style: str
    duration_sec: float
    period_sec: float
    cone_scale: float = 1.0
    phase_direction: float = 1.0


@dataclass(frozen=True)
class TimedTrajectory:
    start_sec: float
    profile: MotionProfile
    trajectory: RCMConeOrbitTrajectory


class FixedTcpDemo:
    def __init__(self, arm, *, config: DemoConfig, log_dir: Path):
        self.arm = arm
        self.config = config
        self.logger = CsvPoseLogger(log_dir)
        self.log_path = self.logger.path
        self.fixed_xyz: list[float] | None = None
        self.center_rpy: list[float] | None = None
        self.trajectory: RCMConeOrbitTrajectory | None = None
        self.trajectory_sequence: list[TimedTrajectory] = []
        self.last_target_joints: list[float] | None = None
        self.last_print = 0.0
        self.last_loop = time.monotonic()
        self.stop_requested = threading.Event()

    def _require_running(self) -> None:
        if self.stop_requested.is_set():
            raise SafetyError("fixed TCP demo cancelled")

    def _send_waypoints(self, waypoints):
        self._require_running()
        speed = self.config.execute_speed_percent
        if not math.isfinite(speed) or not 0 < speed <= 0.05:
            raise SafetyError("fixed TCP speed must respect the shared speed envelope")
        return self.arm.set_joint_waypoints(waypoints, speed_percent=speed)

    def initialize(self) -> None:
        self._require_running()
        if self.config.max_cone_deg > self.config.allow_max_cone_deg:
            raise SafetyError("configured cone angle exceeds the allowed safety cap")
        if self.config.start_from_zero:
            self._move_to_zero()
        pos, euler = self.arm.get_ee_pose_euler()
        joints = finite_vector(self.arm.get_joint_positions(), 6, "joint positions")
        target_xyz = pos if self.config.use_current_tcp_xyz else (
            self.config.fixed_xyz or [0.48, 0.0, 0.36]
        )
        self.fixed_xyz = assert_workspace_position(target_xyz)
        self.center_rpy = finite_vector(euler, 3, "TCP Euler angles")
        assert_known_collision_zones(joints)
        self.last_target_joints = list(joints)
        self._move_to_center_pose()
        cone_angle = math.radians(self.config.max_cone_deg)
        self.trajectory = RCMConeOrbitTrajectory(
            self.center_rpy,
            cone_angle_rad=cone_angle,
            period_sec=self.config.period_sec,
            duration_sec=self.config.duration_sec,
            ramp_sec=self.config.ramp_sec,
            cone_pulse_fraction=self.config.cone_pulse_fraction,
            phase_wobble_rad=self.config.phase_wobble_rad,
            path_style=self.config.path_style,
        )
        self._configure_trajectory_sequence(self.config.max_cone_deg)
        source = "current TCP" if self.config.use_current_tcp_xyz else "configured fixed point"
        print(f"Fixed TCP locked ({source})")
        print(f"  XYZ: {self._fmt(self.fixed_xyz)} m")
        print(f"  RPY: {self._fmt_deg(self.center_rpy)} deg")
        print(f"  Joint: {self._fmt_deg(joints)} deg")
        print(f"  CSV log: {self.log_path}")

    def _move_to_zero(self) -> None:
        zero = [0.0] * 6
        self._wait_for_joint_state("before zero start pose")
        print(f"Moving to zero start pose: {self._fmt_deg(zero)} deg")
        if self.config.execute and not self.config.dry_run:
            self._require_running()
            self._send_waypoints([zero])
        self.last_target_joints = list(zero)

    def _wait_for_joint_state(self, label: str) -> list[float]:
        deadline = time.monotonic() + self.config.startup_state_timeout_sec
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            self._require_running()
            try:
                joints = finite_vector(self.arm.get_joint_positions(), 6, "joint positions")
                assert_joint_limits(joints)
                return joints
            except Exception as exc:
                last_error = exc
                time.sleep(self.config.startup_state_poll_sec)
        detail = f": {last_error}" if last_error is not None else ""
        raise SafetyError(f"joint state was not available {label} within "
                          f"{self.config.startup_state_timeout_sec:.1f}s{detail}")

    def _move_to_center_pose(self) -> None:
        if self.fixed_xyz is None or self.center_rpy is None:
            raise RuntimeError("fixed point is not initialized")
        current_joints = finite_vector(self.arm.get_joint_positions(), 6, "joint positions")
        q_center, ok = self.arm.solve_ik(
            self.fixed_xyz,
            euler_to_quaternion_wxyz(self.center_rpy),
            q_seed=current_joints,
        )
        if not ok:
            raise SafetyError("IK failed for fixed TCP center pose")
        q_center = assert_known_collision_zones(q_center)
        print(f"Moving to fixed TCP center pose: {self._fmt_deg(q_center)} deg")
        if self.config.execute and not self.config.dry_run:
            self._require_running()
            self._send_waypoints([q_center])
        self.last_target_joints = list(q_center)

    def should_continue(self, elapsed_sec: float) -> bool:
        return elapsed_sec < self.config.duration_sec

    def run_one_step(self, elapsed_sec: float) -> None:
        if self.fixed_xyz is None or self.center_rpy is None or self.trajectory is None:
            raise RuntimeError("demo is not initialized")
        target_rpy = self.trajectory.sample(elapsed_sec)
        assert_orientation_delta(self.center_rpy, target_rpy, math.pi)
        current_joints = finite_vector(self.arm.get_joint_positions(), 6, "joint positions")
        seed_joints = self.last_target_joints or current_joints
        quat = euler_to_quaternion_wxyz(target_rpy)
        q_target, ok = self.arm.solve_ik(self.fixed_xyz, quat, q_seed=seed_joints)
        if not ok:
            self._record(target_rpy, current_joints, loop_hz=0.0, ik_status="failed")
            raise SafetyError("IK failed for fixed TCP target")
        q_target = assert_known_collision_zones(q_target)
        assert_step_size(seed_joints, q_target, math.radians(self.config.max_joint_step_deg))
        if self.config.execute and not self.config.dry_run:
            self._require_running()
            self._send_waypoints([current_joints, q_target])
        self.last_target_joints = list(q_target)
        now = time.monotonic()
        loop_hz = 1.0 / max(now - self.last_loop, 1e-6)
        self.last_loop = now
        self._record(target_rpy, q_target, loop_hz=loop_hz, ik_status="ok")
        actual_xyz, actual_rpy = self._actual_pose()
        error_mm = self._position_error_mm(actual_xyz)
        if self.config.execute and not self.config.dry_run and error_mm > self.config.max_position_error_mm:
            raise SafetyError(
                f"TCP position error {error_mm:.1f} mm exceeds "
                f"{self.config.max_position_error_mm:.1f} mm; stopping demo"
            )
        if now - self.last_print >= self.config.print_interval_sec:
            self.last_print = now
            print(f"TCP target: {self._fmt(self.fixed_xyz)}")
            print(f"TCP actual: {self._fmt(actual_xyz)}")
            print(f"Position error: {error_mm:.2f} mm")
            print(f"RPY: {self._fmt_deg(actual_rpy)} deg")
            print(f"Loop: {loop_hz:.1f} Hz")

    def run_forever(self) -> None:
        self.initialize()
        plan = self.plan_full_trajectory_with_auto_amplitude()
        print(
            f"Trajectory precheck OK: {len(plan)} waypoints, "
            f"{self.config.duration_sec:.1f}s planned path, fixed tip {self._fmt(self.fixed_xyz or [])} m"
        )
        if self.config.execute and not self.config.dry_run:
            self._execute_planned_trajectory(plan)
        else:
            self._record_dry_run_plan(plan)
        self._return_to_home()
        print(f"Demo duration reached ({self.config.duration_sec:.1f}s); stopping new commands.")

    def plan_full_trajectory_with_auto_amplitude(self) -> list[PlannedPoint]:
        if self.center_rpy is None or self.last_target_joints is None:
            raise RuntimeError("demo is not initialized")
        requested = self.config.max_cone_deg
        candidates = [
            requested,
            min(requested, 48.0),
            min(requested, 46.0),
            min(requested, 45.0),
            min(requested, 44.0),
            min(requested, 42.0),
            min(requested, 40.0),
            min(requested, 38.0),
            min(requested, 36.0),
            min(requested, 35.0),
            min(requested, 32.0),
            min(requested, 30.0),
            min(requested, 28.0),
            min(requested, 26.0),
            min(requested, 25.0),
            min(requested, 24.0),
            min(requested, 22.0),
            min(requested, 20.0),
            min(requested, self.config.min_auto_cone_deg),
        ]
        candidates = sorted({round(value, 3) for value in candidates}, reverse=True)
        last_error: Exception | None = None
        center_joints = list(self.last_target_joints)
        for cone_deg in candidates:
            if cone_deg < self.config.min_auto_cone_deg:
                continue
            self._configure_trajectory_sequence(cone_deg)
            self.last_target_joints = list(center_joints)
            try:
                plan = self.plan_full_trajectory()
            except SafetyError as exc:
                last_error = exc
                print(f"Trajectory precheck rejected cone {cone_deg:.1f}deg: {exc}")
                continue
            names = ", ".join(item.profile.name for item in self.trajectory_sequence)
            print(f"Using RCM cone angle: {cone_deg:.1f} deg")
            print(f"Motion sequence: {names}")
            return plan
        detail = f": {last_error}" if last_error is not None else ""
        raise SafetyError(
            f"no safe fixed-TCP RCM cone trajectory found down to "
            f"{self.config.min_auto_cone_deg:.1f}deg{detail}"
        )

    def _return_to_home(self) -> None:
        self._require_running()
        zero = [0.0] * 6
        print(f"Returning to zero home pose: {self._fmt_deg(zero)} deg")
        if self.config.execute and not self.config.dry_run:
            current_joints = finite_vector(self.arm.get_joint_positions(), 6, "joint positions")
            assert_known_collision_zones(current_joints)
            self._require_running()
            self._send_waypoints([current_joints, zero])
        self.last_target_joints = list(zero)

    def plan_full_trajectory(self) -> list[PlannedPoint]:
        if self.fixed_xyz is None or self.center_rpy is None or self.trajectory is None:
            raise RuntimeError("demo is not initialized")
        seed = list(self.last_target_joints or finite_vector(self.arm.get_joint_positions(), 6, "joint positions"))
        initial_seed = list(seed)
        sample_count = max(2, int(self.config.duration_sec * self.config.control_hz) + 1)
        dt = self.config.duration_sec / (sample_count - 1)
        plan: list[PlannedPoint] = []
        for index in range(sample_count):
            self._require_running()
            elapsed = index * dt
            target_rpy = self._sample_target_rpy(elapsed)
            assert_orientation_delta(self.center_rpy, target_rpy, math.pi)
            q_target, ok = self.arm.solve_ik(
                self.fixed_xyz,
                euler_to_quaternion_wxyz(target_rpy),
                q_seed=seed,
            )
            if not ok:
                self._record(target_rpy, seed, loop_hz=0.0, ik_status="failed")
                raise SafetyError(f"IK failed while prechecking waypoint {index}/{sample_count - 1}")
            q_target = assert_known_collision_zones(q_target)
            assert_step_size(seed, q_target, math.radians(self.config.max_joint_step_deg))
            if plan:
                previous = plan[-2].joints if len(plan) >= 2 else initial_seed
                assert_joint_acceleration(
                    previous,
                    plan[-1].joints,
                    q_target,
                    math.radians(self.config.max_joint_accel_step_deg),
                )
            plan.append(PlannedPoint(elapsed, target_rpy, q_target))
            seed = list(q_target)
        self.last_target_joints = list(plan[-1].joints)
        return plan

    def _execute_planned_trajectory(self, plan: list[PlannedPoint]) -> None:
        self._require_running()
        stop_event = threading.Event()
        monitor = threading.Thread(
            target=self._monitor_execution,
            args=(stop_event,),
            name="fixed-tcp-monitor",
            daemon=True,
        )
        monitor.start()
        try:
            self._require_running()
            duration = self._send_waypoints([point.joints for point in plan])
            duration_text = "unknown" if duration is None else f"{float(duration):.2f}s"
            print(
                f"SDK accepted bounded-speed trajectory: duration={duration_text}"
            )
        finally:
            stop_event.set()
            monitor.join(timeout=1.0)

    def _monitor_execution(self, stop_event: threading.Event) -> None:
        if self.fixed_xyz is None or (self.trajectory is None and not self.trajectory_sequence):
            return
        started = time.monotonic()
        next_print = 0.0
        while not stop_event.is_set() and not self.stop_requested.is_set():
            now = time.monotonic()
            elapsed = min(now - started, self.config.duration_sec)
            target_rpy = self._sample_target_rpy(elapsed)
            joints = finite_vector(self.arm.get_joint_positions(), 6, "joint positions")
            loop_hz = 1.0 / max(now - self.last_loop, 1e-6)
            self.last_loop = now
            self._record(target_rpy, joints, loop_hz=loop_hz, ik_status="monitor")
            actual_xyz, actual_rpy = self._actual_pose()
            error_mm = self._position_error_mm(actual_xyz)
            if error_mm > self.config.max_position_error_mm:
                print(
                    f"WARNING: TCP position error {error_mm:.1f} mm exceeds "
                    f"{self.config.max_position_error_mm:.1f} mm"
                )
            if now >= next_print:
                next_print = now + self.config.print_interval_sec
                print(f"TCP target: {self._fmt(self.fixed_xyz)}")
                print(f"TCP actual: {self._fmt(actual_xyz)}")
                print(f"Position error: {error_mm:.2f} mm")
                print(f"RPY: {self._fmt_deg(actual_rpy)} deg")
                print(f"Loop: {loop_hz:.1f} Hz")
            stop_event.wait(1.0 / self.config.control_hz)

    def _record_dry_run_plan(self, plan: list[PlannedPoint]) -> None:
        last = self.last_loop
        for point in plan:
            loop_hz = self.config.control_hz if last else 0.0
            self._record(point.target_rpy, point.joints, loop_hz=loop_hz, ik_status="prechecked")
        print("DRY-RUN trajectory was fully prechecked; no real motion was sent.")

    def _configure_trajectory_sequence(self, cone_deg: float) -> None:
        if self.center_rpy is None:
            raise RuntimeError("center RPY is not initialized")
        profiles = self._motion_profiles()
        start = 0.0
        sequence: list[TimedTrajectory] = []
        for profile in profiles:
            trajectory = RCMConeOrbitTrajectory(
                self.center_rpy,
                cone_angle_rad=math.radians(cone_deg * profile.cone_scale),
                period_sec=profile.period_sec,
                duration_sec=None,
                ramp_sec=0.0,
                cone_pulse_fraction=self.config.cone_pulse_fraction,
                phase_wobble_rad=self.config.phase_wobble_rad,
                path_style=profile.path_style,
                phase_direction=profile.phase_direction,
            )
            sequence.append(TimedTrajectory(start, profile, trajectory))
            start += profile.duration_sec
        self.trajectory_sequence = sequence
        self.trajectory = sequence[0].trajectory if sequence else None

    def _motion_profiles(self) -> list[MotionProfile]:
        segment = self.config.duration_sec / 8.0
        return [
            MotionProfile("cone_clockwise", "orbit", segment, 5.0, cone_scale=1.0, phase_direction=1.0),
            MotionProfile("cardinal_cross", "cardinal_cross", segment, 8.0, cone_scale=0.65, phase_direction=1.0),
            MotionProfile("irregular_shell", "irregular_shell", segment, 8.0, cone_scale=0.78, phase_direction=1.0),
            MotionProfile("flower_envelope", "lissajous", segment, 6.0, cone_scale=0.75, phase_direction=1.0),
            MotionProfile("nod_shake", "nod_shake", segment, 6.0, cone_scale=0.62, phase_direction=1.0),
            MotionProfile("spiral_breathe", "spiral_breathe", segment, 6.5, cone_scale=0.70, phase_direction=1.0),
            MotionProfile("cone_counterclockwise", "orbit", segment, 4.8, cone_scale=0.85, phase_direction=-1.0),
            MotionProfile("wide_flower_finish", "lissajous", self.config.duration_sec - 7.0 * segment, 7.0, cone_scale=0.70, phase_direction=-1.0),
        ]

    def _sample_target_rpy(self, elapsed_sec: float) -> list[float]:
        if self.center_rpy is None:
            raise RuntimeError("center RPY is not initialized")
        if not self.trajectory_sequence:
            if self.trajectory is None:
                raise RuntimeError("trajectory is not initialized")
            raw = self.trajectory.sample(elapsed_sec)
            return self._blend_rpy(self.center_rpy, raw, self._global_motion_scale(elapsed_sec))

        selected_index = len(self.trajectory_sequence) - 1
        for index, item in enumerate(self.trajectory_sequence):
            if elapsed_sec >= item.start_sec:
                selected_index = index
            else:
                break

        selected = self.trajectory_sequence[selected_index]
        local_elapsed = elapsed_sec - selected.start_sec
        raw = selected.trajectory.sample(local_elapsed)

        transition = max(0.0, min(self.config.transition_sec, selected.profile.duration_sec * 0.45))
        if transition > 0.0 and selected_index + 1 < len(self.trajectory_sequence):
            end_sec = selected.start_sec + selected.profile.duration_sec
            remaining = end_sec - elapsed_sec
            if 0.0 <= remaining < transition:
                next_item = self.trajectory_sequence[selected_index + 1]
                next_raw = next_item.trajectory.sample(elapsed_sec - next_item.start_sec)
                raw = self._blend_rpy(raw, next_raw, self._smoothstep(1.0 - remaining / transition))

        return self._blend_rpy(self.center_rpy, raw, self._global_motion_scale(elapsed_sec))

    def _global_motion_scale(self, elapsed_sec: float) -> float:
        if self.config.ramp_sec <= 0.0:
            return 1.0
        scale = self._smoothstep(elapsed_sec / self.config.ramp_sec)
        scale = min(scale, self._smoothstep((self.config.duration_sec - elapsed_sec) / self.config.ramp_sec))
        return max(0.0, min(1.0, scale))

    @staticmethod
    def _smoothstep(value: float) -> float:
        value = max(0.0, min(1.0, value))
        return value * value * (3.0 - 2.0 * value)

    @staticmethod
    def _blend_rpy(start: list[float], end: list[float], fraction: float) -> list[float]:
        fraction = max(0.0, min(1.0, fraction))
        return [
            start_value + (end_value - start_value) * fraction
            for start_value, end_value in zip(start, end)
        ]

    def close(self) -> None:
        try:
            self.logger.close()
        finally:
            cleanup = getattr(self.arm, "cleanup", None)
            if callable(cleanup):
                cleanup()

    def _actual_pose(self) -> tuple[list[float], list[float]]:
        pos, rpy = self.arm.get_ee_pose_euler()
        return finite_vector(pos, 3, "actual TCP position"), finite_vector(rpy, 3, "actual RPY")

    def _record(self, target_rpy: list[float], joints: list[float], *, loop_hz: float, ik_status: str) -> None:
        actual_xyz, actual_rpy = self._actual_pose()
        self.logger.write(
            timestamp=time.time(),
            target_xyz=self.fixed_xyz or [math.nan] * 3,
            actual_xyz=actual_xyz,
            error_mm=self._position_error_mm(actual_xyz),
            target_rpy=target_rpy,
            actual_rpy=actual_rpy,
            joints=joints,
            loop_hz=loop_hz,
            ik_status=ik_status,
        )

    def _position_error_mm(self, actual_xyz: list[float]) -> float:
        fixed = self.fixed_xyz or [math.nan] * 3
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(actual_xyz, fixed))) * 1000.0

    @staticmethod
    def _fmt(values: list[float]) -> str:
        return "[" + ", ".join(f"{value:.4f}" for value in values) + "]"

    @staticmethod
    def _fmt_deg(values: list[float]) -> str:
        return "[" + ", ".join(f"{math.degrees(value):.2f}" for value in values) + "]"
