import logging
import os
import signal
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

import numpy as np

from startouchclass import SingleArm, euler_to_quaternion


# 测试宏定义。测试人员只改这里，不需要传命令行参数。

# 真机模式使用的 CAN 网口名。
CAN_INTERFACE = "can0"

# 是否启用 CAN-FD；当前 Startouch 板卡默认使用普通 CAN。
ENABLE_FD = False

# 是否包含夹爪测试和夹爪随动指令。
GRIPPER_ENABLED = True

# True 表示仿真模式：正常跑 IK、规划和 API 流程，但不打开 CAN、不下发硬件指令。
# False 表示真机模式：打开 CAN，并向机械臂和夹爪下发真实指令。
SIMULATION_ONLY = False

# 底层 SDK 的 dry_run 开关；除非调试 SDK 内部，否则保持等于 SIMULATION_ONLY。
DRY_RUN = SIMULATION_ONLY

# True 表示一直循环完整测试，直到 Ctrl+C；False 表示只跑有限次数。
RUN_FOREVER = True

# 当 RUN_FOREVER=False 且 FULL_TEST_LOOP_COUNT<=0 时使用的完整测试循环次数。
MAX_LOOP_COUNT_WHEN_NOT_FOREVER = 1

# 本地静态预检使用的环境变量名；启用后不创建 SingleArm，也不会访问 CAN。
LOCAL_PREFLIGHT_ONLY_ENV = "STARTOUCH_LOCAL_PREFLIGHT_ONLY"

# 完整测试循环次数；设为 1 表示跑一遍完整流程，设为 <=0 则使用 MAX_LOOP_COUNT_WHEN_NOT_FOREVER。
FULL_TEST_LOOP_COUNT = 1

# 回零关节位置；每组测试前后和 Ctrl+C 后都会用到。
HOME_JOINTS = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

# 主测试关节路点，单位为弧度。
JOINT_WAYPOINTS = [
    [0.0, 1.54, -3.0, 1.29, 0.0, 0.0],
    [2.7, 1.54, -3.0, 1.29, 1.6, -2.7],
    [-2.7, 1.54, -3.0, 0.0, -1.6, 2.7],
    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    [0.0, 3.2, -1.5, 0.0, 0.0, 0.0],
    [0.0, -0.13, 0.0, -1.29, 0.0, 0.0],
]

# 与 JOINT_WAYPOINTS 对齐的夹爪归一化位置；长度必须一致。
GRIPPER_POSITIONS = [1.0, 0.65, 0.35, 1.0, 0.2, 0.8]

# 回零动作时间，单位秒。
HOME_TIME_SEC = 3.0

# time_sec 模式下关节路点整段轨迹的总时间，单位秒。
JOINT_WAYPOINT_TIME_SEC = 30.0

# speed_percent 模式下的速度比例，范围必须是 (0, 1]。
SPEED_PERCENT = 0.3

# 夹爪接口测试组的循环次数。
GRIPPER_INTERFACE_TEST_CYCLES = 1

# time_sec 模式下 move_joint_waypoints_with_gripper 的循环次数。
JOINT_WITH_GRIPPER_TIME_SEC_CYCLES = 1

# speed_percent 模式下 move_joint_waypoints_with_gripper 的循环次数。
JOINT_WITH_GRIPPER_SPEED_PERCENT_CYCLES = 1

# 是否运行 move_l 测试；当前关闭，因为还原出的笛卡尔直线路径可能 IK 不可达。
MOVE_L_TEST_ENABLED = False

# MOVE_L_TEST_ENABLED=True 时，move_l 的 time_sec 测试循环次数。
MOVE_L_TIME_SEC_CYCLES = 1

# MOVE_L_TEST_ENABLED=True 时，move_l 的 speed_percent 测试循环次数。
MOVE_L_SPEED_PERCENT_CYCLES = 1

# 是否运行 move_p 测试；当前关闭，因为该路径可能在插值采样点 IK 失败。
MOVE_P_TEST_ENABLED = False

# MOVE_P_TEST_ENABLED=True 时，move_p 的 time_sec 测试循环次数。
MOVE_P_TIME_SEC_CYCLES = 1

# MOVE_P_TEST_ENABLED=True 时，move_p 的 speed_percent 测试循环次数。
MOVE_P_SPEED_PERCENT_CYCLES = 1

# 是否运行“还原位姿 -> IK -> 关节路点”的测试。
POSE_IK_JOINT_TEST_ENABLED = False

# POSE_IK_JOINT_TEST_ENABLED=True 时，位姿 IK 关节路点的 time_sec 测试循环次数。
POSE_IK_JOINT_TIME_SEC_CYCLES = 1

# POSE_IK_JOINT_TEST_ENABLED=True 时，位姿 IK 关节路点的 speed_percent 测试循环次数。
POSE_IK_JOINT_SPEED_PERCENT_CYCLES = 1

# move_l 的混合半径；严格直线段通常设为 0。
MOVE_L_BLEND_RADIUS_M = 0.0

# move_p 的混合半径，单位米。
MOVE_P_BLEND_RADIUS_M = 0.002

# IK 验证时允许的笛卡尔位置残差，单位米。
POSITION_TOLERANCE_M = 0.003

# IK 验证时允许的笛卡尔姿态残差，单位弧度。
ORIENTATION_TOLERANCE_RAD = 0.05

# 从规划关节采样点还原 FK 位姿时，允许的最大关节误差，单位弧度。
POSE_RESTORE_MAX_Q_ERROR_RAD = 0.02

# 每个夹爪指令后的等待时间，单位秒。
GRIPPER_SETTLE_SEC = 0.15

# 夹爪张开距离指令，单位米。
GRIPPER_DISTANCE_OPEN_M = 0.07

# 夹爪半开距离指令，单位米。
GRIPPER_DISTANCE_HALF_M = 0.035

# 夹爪接近闭合距离指令，单位米。
GRIPPER_DISTANCE_CLOSED_M = 0.005

# 夹爪距离控制测试使用的刚度参数。
GRIPPER_KP = 8.0

# 夹爪距离控制测试使用的阻尼参数。
GRIPPER_KD = 0.1

# 轮转日志目录。
LOG_DIR = Path(__file__).resolve().parent / "logs"

# 主轮转日志文件路径。
LOG_FILE = LOG_DIR / "joint_waypoints_auto.log"

# 单个日志文件达到该大小后轮转。
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024

# 保留的轮转日志备份数量。
LOG_FILE_BACKUP_COUNT = 5

# 用于本地限幅统计的 SDK 运动学和安全配置文件。
CONFIG_PATH = Path(__file__).resolve().parents[1] / "src" / "config" / "robot_kinematics.yaml"

# 估算关节速度超过配置最大速度的该倍率时报警。
VELOCITY_WARN_RATIO = 1.0

# 估算关节加速度超过配置最大加速度的该倍率时报警。
ACCELERATION_WARN_RATIO = 1.0

# 非零关节速度最大值和最小值的比值超过该值时报警。
BALANCE_VELOCITY_RATIO_WARN = 5.0


_shutdown_requested = threading.Event()
_cleanup_started = threading.Event()
_return_home_started = threading.Event()
_active_arm_lock = threading.Lock()
_active_arm: Optional[SingleArm] = None
_logger: Optional[logging.Logger] = None


@dataclass
class MotionResult:
    value: object = None
    error: Optional[BaseException] = None
    traceback_text: str = ""


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("joint_waypoints_auto")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUP_COUNT,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def log() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger


def flush_logs() -> None:
    for handler in log().handlers:
        handler.flush()


def request_shutdown(signum, frame):  # noqa: ARG001
    _shutdown_requested.set()


def install_signal_handlers() -> None:
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


def set_active_arm(arm: Optional[SingleArm]) -> None:
    global _active_arm
    with _active_arm_lock:
        _active_arm = arm


def cleanup_active_arm() -> None:
    if _cleanup_started.is_set():
        return
    _cleanup_started.set()
    with _active_arm_lock:
        arm = _active_arm
    if arm is None:
        return
    try:
        log().info("cleanup active arm")
        arm.cleanup()
    except BaseException:  # noqa: BLE001
        log().exception("cleanup active arm failed")
    finally:
        set_active_arm(None)
        flush_logs()


def create_arm() -> SingleArm:
    return SingleArm(
        can_interface_=CAN_INTERFACE,
        gripper=GRIPPER_ENABLED,
        enable_fd_=ENABLE_FD,
        dry_run=DRY_RUN,
    )


def return_home_after_interrupt() -> None:
    if _return_home_started.is_set():
        return
    _return_home_started.set()
    log().info("return home after interrupt without pre-cleanup")
    with _active_arm_lock:
        home_arm = _active_arm
    created_new_arm = home_arm is None
    if home_arm is None:
        log().warning("no active arm found during interrupt; create a new arm for return home")
        home_arm = create_arm()
    try:
        home_arm.set_joint(HOME_JOINTS, tf=HOME_TIME_SEC)
        time.sleep(HOME_TIME_SEC + 0.5)
        if GRIPPER_ENABLED:
            home_arm.openGripper()
    except BaseException:  # noqa: BLE001
        log().exception("return home after interrupt failed")
        raise
    finally:
        if created_new_arm:
            try:
                home_arm.cleanup()
            finally:
                flush_logs()
        else:
            cleanup_active_arm()


def run_interruptible_call(label: str, call_fn: Callable, *args, **kwargs):
    result = MotionResult()

    def worker() -> None:
        try:
            result.value = call_fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            result.error = exc
            result.traceback_text = traceback.format_exc()

    log().info("START %s", label)
    thread = threading.Thread(target=worker, name=label, daemon=True)
    thread.start()
    while thread.is_alive():
        thread.join(timeout=0.05)
        if _shutdown_requested.is_set():
            log().warning("interrupt during %s; return home will reuse active arm", label)
            raise KeyboardInterrupt
    if result.error is not None:
        log().error("FAIL %s: %s", label, result.error)
        log().error("%s", result.traceback_text.rstrip())
        flush_logs()
        raise result.error
    if isinstance(result.value, (int, float, np.floating)) and not isinstance(result.value, bool):
        log().info("DONE %s duration=%.6f", label, float(result.value))
    else:
        log().info("DONE %s", label)
    flush_logs()
    return result.value


def interruptible_sleep(seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while not _shutdown_requested.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return
        time.sleep(min(0.05, remaining))
    raise KeyboardInterrupt


def load_limit_vector(section: str, key: str, fallback: Sequence[float]) -> np.ndarray:
    try:
        import yaml  # type: ignore

        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        values = data.get(section, {}).get(key, fallback)
        return np.asarray(values, dtype=float)
    except BaseException:  # noqa: BLE001
        return np.asarray(fallback, dtype=float)


def validate_joint_waypoints(label: str, waypoints: Sequence[Sequence[float]]) -> np.ndarray:
    arr = np.asarray(waypoints, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 6:
        raise ValueError(f"{label} must have shape (N, 6), got {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{label} contains non-finite values")
    return arr


def validate_gripper_positions() -> np.ndarray:
    values = np.asarray(GRIPPER_POSITIONS, dtype=float).reshape(-1)
    if len(values) != len(JOINT_WAYPOINTS):
        raise ValueError("GRIPPER_POSITIONS length must match JOINT_WAYPOINTS")
    if not np.all(np.isfinite(values)):
        raise ValueError("GRIPPER_POSITIONS contains non-finite values")
    if np.any(values < 0.0) or np.any(values > 1.0):
        raise ValueError("GRIPPER_POSITIONS must be in [0, 1]")
    return values


def summarize_joint_path(label: str, waypoints: np.ndarray, total_time_sec: float) -> None:
    if len(waypoints) < 2:
        log().info("%s has fewer than two points; skip speed check", label)
        return
    max_vel_limits = load_limit_vector(
        "joint_trajectory",
        "max_vel_limits",
        [5.5, 5.5, 5.5, 20.9, 20.9, 20.9],
    )
    max_acc_limits = load_limit_vector(
        "joint_trajectory",
        "max_acc_limits",
        [500.0, 500.0, 800.0, 2000.0, 2000.0, 2000.0],
    )
    segment_count = len(waypoints) - 1
    segment_dt = float(total_time_sec) / float(segment_count)
    if segment_dt <= 0.0:
        raise ValueError(f"{label} total_time_sec must be positive")

    dq = np.diff(waypoints, axis=0)
    velocity = dq / segment_dt
    max_abs_velocity = np.max(np.abs(velocity), axis=0)
    velocity_ratio = max_abs_velocity / np.maximum(max_vel_limits, 1e-9)

    log().info("%s segment_dt=%.6f", label, segment_dt)
    log().info("%s max_abs_velocity=%s", label, np.round(max_abs_velocity, 6).tolist())
    log().info("%s velocity_ratio=%s", label, np.round(velocity_ratio, 6).tolist())

    if np.any(velocity_ratio > VELOCITY_WARN_RATIO):
        log().warning("%s velocity exceeds configured limit", label)

    nonzero = max_abs_velocity[max_abs_velocity > 1e-9]
    if len(nonzero) > 1 and float(np.max(nonzero) / np.min(nonzero)) > BALANCE_VELOCITY_RATIO_WARN:
        log().warning("%s joint velocity spread is high", label)

    if len(velocity) < 2:
        return
    acceleration = np.diff(velocity, axis=0) / segment_dt
    max_abs_acceleration = np.max(np.abs(acceleration), axis=0)
    acceleration_ratio = max_abs_acceleration / np.maximum(max_acc_limits, 1e-9)
    log().info("%s max_abs_acceleration=%s", label, np.round(max_abs_acceleration, 6).tolist())
    log().info("%s acceleration_ratio=%s", label, np.round(acceleration_ratio, 6).tolist())
    if np.any(acceleration_ratio > ACCELERATION_WARN_RATIO):
        log().warning("%s acceleration exceeds configured limit", label)


def summarize_planned_samples(label: str, rows: Iterable[Sequence[float]]) -> np.ndarray:
    arr = np.asarray(list(rows), dtype=float)
    if arr.ndim != 2 or arr.shape[1] < 14:
        raise ValueError(f"{label} planned rows must have at least 14 columns, got {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{label} planned rows contain non-finite values")

    t = arr[:, 0]
    q = arr[:, 1:7]
    poses = arr[:, 7:13]
    dt = np.diff(t)
    if len(dt) and np.any(dt <= 0.0):
        raise ValueError(f"{label} planned timestamps are not strictly increasing")
    if len(dt):
        dq = np.diff(q, axis=0)
        vel = dq / dt[:, None]
        max_abs_vel = np.max(np.abs(vel), axis=0)
        log().info("%s planned max_abs_velocity=%s", label, np.round(max_abs_vel, 6).tolist())
        if len(vel) >= 2:
            acc = np.diff(vel, axis=0) / dt[1:, None]
            log().info(
                "%s planned max_abs_acceleration=%s",
                label,
                np.round(np.max(np.abs(acc), axis=0), 6).tolist(),
            )
        pos_speed = np.linalg.norm(np.diff(poses[:, :3], axis=0), axis=1) / dt
        euler_speed = np.linalg.norm(np.diff(poses[:, 3:6], axis=0), axis=1) / dt
        log().info("%s planned max_position_speed=%.6f", label, float(np.max(pos_speed)))
        log().info("%s planned max_euler_speed=%.6f", label, float(np.max(euler_speed)))
    return arr


def restore_poses_from_joint_plan(arm: SingleArm) -> List[List[float]]:
    rows = run_interruptible_call(
        "plan restore poses from original joint waypoints",
        arm.plan_joint_waypoints_with_gripper,
        HOME_JOINTS,
        JOINT_WAYPOINTS,
        GRIPPER_POSITIONS,
        time_sec=JOINT_WAYPOINT_TIME_SEC,
    )
    arr = summarize_planned_samples("restore poses plan", rows)
    q_samples = arr[:, 1:7]
    poses = []
    for index, waypoint in enumerate(np.asarray(JOINT_WAYPOINTS, dtype=float)):
        distances = np.linalg.norm(q_samples - waypoint, axis=1)
        nearest = int(np.argmin(distances))
        q_error = float(distances[nearest])
        if q_error > POSE_RESTORE_MAX_Q_ERROR_RAD:
            raise RuntimeError(
                f"pose restore failed at waypoint {index}: nearest q error {q_error:.6f} rad"
            )
        pose = arr[nearest, 7:13].astype(float).tolist()
        poses.append(pose)
        log().info("restored pose[%d] q_error=%.6f pose=%s", index, q_error, np.round(pose, 6))
    return poses


def solve_pose_waypoints_to_joints(arm: SingleArm, poses: Sequence[Sequence[float]]) -> List[List[float]]:
    q_seed = np.asarray(HOME_JOINTS, dtype=float)
    solved = []
    for index, pose in enumerate(np.asarray(poses, dtype=float)):
        quat = euler_to_quaternion(float(pose[3]), float(pose[4]), float(pose[5]))
        q, ok = run_interruptible_call(
            f"pose IK waypoint {index}",
            arm.solve_ik,
            pose[:3].tolist(),
            quat.tolist(),
            q_seed.tolist(),
        )
        if not ok:
            raise RuntimeError(f"pose IK failed at waypoint {index}: pose={pose.tolist()} seed={q_seed.tolist()}")
        q_seed = np.asarray(q, dtype=float)
        if q_seed.shape != (6,) or not np.all(np.isfinite(q_seed)):
            raise RuntimeError(f"pose IK returned invalid q at waypoint {index}: {q}")
        solved.append(q_seed.tolist())
        log().info("pose IK waypoint %d q=%s", index, np.round(q_seed, 6).tolist())
    return solved


def run_gripper_interface_tests(arm: SingleArm, cycle_count: int) -> None:
    if not GRIPPER_ENABLED:
        log().info("skip gripper tests because GRIPPER_ENABLED=False")
        return
    tests = [
        ("gripper openGripper", arm.openGripper, ()),
        ("gripper closeGripper", arm.closeGripper, ()),
        ("gripper setGripperPosition close", arm.setGripperPosition, (0.0,)),
        ("gripper setGripperPosition half", arm.setGripperPosition, (0.5,)),
        ("gripper setGripperPosition open", arm.setGripperPosition, (1.0,)),
        ("gripper setGripperDistance default", arm.setGripperDistance, (GRIPPER_DISTANCE_HALF_M,)),
        ("gripper setGripperDistance kp", arm.setGripperDistance, (GRIPPER_DISTANCE_OPEN_M, GRIPPER_KP)),
        (
            "gripper setGripperDistance kp kd",
            arm.setGripperDistance,
            (GRIPPER_DISTANCE_CLOSED_M, GRIPPER_KP, GRIPPER_KD),
        ),
        (
            "gripper setGripperDistance_raw",
            arm.setGripperDistance_raw,
            (GRIPPER_DISTANCE_HALF_M, GRIPPER_KP, GRIPPER_KD),
        ),
    ]
    for cycle in range(1, max(1, cycle_count) + 1):
        for label, call_fn, args in tests:
            run_interruptible_call(f"{label} cycle {cycle}", call_fn, *args)
            interruptible_sleep(GRIPPER_SETTLE_SEC)


def run_joint_waypoint_with_gripper_tests(
    arm: SingleArm,
    mode_label: str,
    cycle_count: int,
    **motion_kwargs,
) -> None:
    plan_rows = run_interruptible_call(
        f"preplan joint_waypoints_with_gripper {mode_label}",
        arm.plan_joint_waypoints_with_gripper,
        HOME_JOINTS,
        JOINT_WAYPOINTS,
        GRIPPER_POSITIONS,
        **motion_kwargs,
    )
    summarize_planned_samples(f"joint_waypoints_with_gripper {mode_label}", plan_rows)
    for cycle in range(1, max(1, cycle_count) + 1):
        run_interruptible_call(
            f"move_joint_waypoints_with_gripper {mode_label} cycle {cycle}",
            arm.move_joint_waypoints_with_gripper,
            JOINT_WAYPOINTS,
            GRIPPER_POSITIONS,
            **motion_kwargs,
        )


def run_move_l_tests(
    arm: SingleArm,
    poses: Sequence[Sequence[float]],
    mode_label: str,
    cycle_count: int,
    **motion_kwargs,
) -> None:
    for cycle in range(1, max(1, cycle_count) + 1):
        run_interruptible_call(
            f"move_l restored poses {mode_label} cycle {cycle}",
            arm.move_l,
            poses,
            blend_radius_m=MOVE_L_BLEND_RADIUS_M,
            position_tolerance_m=POSITION_TOLERANCE_M,
            orientation_tolerance_rad=ORIENTATION_TOLERANCE_RAD,
            **motion_kwargs,
        )
        samples = arm.get_last_waypoint_command_samples()
        if samples:
            summarize_planned_samples(f"move_l restored poses {mode_label} cycle {cycle}", samples)


def run_move_p_tests(
    arm: SingleArm,
    poses: Sequence[Sequence[float]],
    mode_label: str,
    cycle_count: int,
    **motion_kwargs,
) -> None:
    for cycle in range(1, max(1, cycle_count) + 1):
        run_interruptible_call(
            f"move_p restored poses {mode_label} cycle {cycle}",
            arm.move_p,
            poses,
            blend_radius_m=MOVE_P_BLEND_RADIUS_M,
            position_tolerance_m=POSITION_TOLERANCE_M,
            orientation_tolerance_rad=ORIENTATION_TOLERANCE_RAD,
            **motion_kwargs,
        )
        samples = arm.get_last_waypoint_command_samples()
        if samples:
            summarize_planned_samples(f"move_p restored poses {mode_label} cycle {cycle}", samples)


def run_pose_ik_back_to_joint_tests(
    arm: SingleArm,
    poses: Sequence[Sequence[float]],
    mode_label: str,
    cycle_count: int,
    **motion_kwargs,
) -> None:
    ik_waypoints = solve_pose_waypoints_to_joints(arm, poses)
    plan_rows = run_interruptible_call(
        f"preplan pose IK joint_waypoints_with_gripper {mode_label}",
        arm.plan_joint_waypoints_with_gripper,
        HOME_JOINTS,
        ik_waypoints,
        GRIPPER_POSITIONS,
        **motion_kwargs,
    )
    summarize_planned_samples(f"pose IK joint_waypoints_with_gripper {mode_label}", plan_rows)
    for cycle in range(1, max(1, cycle_count) + 1):
        run_interruptible_call(
            f"move pose IK joint_waypoints_with_gripper {mode_label} cycle {cycle}",
            arm.move_joint_waypoints_with_gripper,
            ik_waypoints,
            GRIPPER_POSITIONS,
            **motion_kwargs,
        )


def run_one_full_test_loop(arm: SingleArm, loop_index: int, restored_poses: Sequence[Sequence[float]]) -> None:
    log().info("========== loop %d begin ==========", loop_index)
    run_interruptible_call("go home before loop", arm.set_joint_waypoints, [HOME_JOINTS], time_sec=HOME_TIME_SEC)

    run_gripper_interface_tests(arm, GRIPPER_INTERFACE_TEST_CYCLES)

    time_kwargs = {"time_sec": JOINT_WAYPOINT_TIME_SEC}
    speed_kwargs = {"speed_percent": SPEED_PERCENT}

    run_joint_waypoint_with_gripper_tests(
        arm,
        "time_sec",
        JOINT_WITH_GRIPPER_TIME_SEC_CYCLES,
        **time_kwargs,
    )
    run_interruptible_call("return home after joint time_sec", arm.set_joint_waypoints, [HOME_JOINTS], time_sec=HOME_TIME_SEC)
    run_joint_waypoint_with_gripper_tests(
        arm,
        "speed_percent",
        JOINT_WITH_GRIPPER_SPEED_PERCENT_CYCLES,
        **speed_kwargs,
    )
    run_interruptible_call("return home after joint speed_percent", arm.set_joint_waypoints, [HOME_JOINTS], time_sec=HOME_TIME_SEC)

    if MOVE_L_TEST_ENABLED:
        run_move_l_tests(arm, restored_poses, "time_sec", MOVE_L_TIME_SEC_CYCLES, **time_kwargs)
        run_interruptible_call("return home after move_l time_sec", arm.set_joint_waypoints, [HOME_JOINTS], time_sec=HOME_TIME_SEC)
        run_move_l_tests(arm, restored_poses, "speed_percent", MOVE_L_SPEED_PERCENT_CYCLES, **speed_kwargs)
        run_interruptible_call("return home after move_l speed_percent", arm.set_joint_waypoints, [HOME_JOINTS], time_sec=HOME_TIME_SEC)
    else:
        log().info("skip move_l tests because MOVE_L_TEST_ENABLED=False")

    if MOVE_P_TEST_ENABLED:
        run_move_p_tests(arm, restored_poses, "time_sec", MOVE_P_TIME_SEC_CYCLES, **time_kwargs)
        run_interruptible_call("return home after move_p time_sec", arm.set_joint_waypoints, [HOME_JOINTS], time_sec=HOME_TIME_SEC)
        run_move_p_tests(arm, restored_poses, "speed_percent", MOVE_P_SPEED_PERCENT_CYCLES, **speed_kwargs)
        run_interruptible_call("return home after move_p speed_percent", arm.set_joint_waypoints, [HOME_JOINTS], time_sec=HOME_TIME_SEC)
    else:
        log().info("skip move_p tests because MOVE_P_TEST_ENABLED=False")

    if POSE_IK_JOINT_TEST_ENABLED:
        run_pose_ik_back_to_joint_tests(
            arm,
            restored_poses,
            "time_sec",
            POSE_IK_JOINT_TIME_SEC_CYCLES,
            **time_kwargs,
        )
        run_interruptible_call("return home after pose IK time_sec", arm.set_joint_waypoints, [HOME_JOINTS], time_sec=HOME_TIME_SEC)
        run_pose_ik_back_to_joint_tests(
            arm,
            restored_poses,
            "speed_percent",
            POSE_IK_JOINT_SPEED_PERCENT_CYCLES,
            **speed_kwargs,
        )
        run_interruptible_call("return home after pose IK speed_percent", arm.set_joint_waypoints, [HOME_JOINTS], time_sec=HOME_TIME_SEC)
    else:
        log().info("skip pose IK joint tests because POSE_IK_JOINT_TEST_ENABLED=False")

    log().info("========== loop %d end ==========", loop_index)


def run_local_preflight_only() -> None:
    log().info("local preflight only: no SingleArm instance, no CAN access")
    log().info("CAN_INTERFACE=%s ENABLE_FD=%s DRY_RUN=%s", CAN_INTERFACE, ENABLE_FD, DRY_RUN)
    waypoints = validate_joint_waypoints("JOINT_WAYPOINTS", JOINT_WAYPOINTS)
    validate_joint_waypoints("HOME_JOINTS", [HOME_JOINTS])
    validate_gripper_positions()

    summarize_joint_path("JOINT_WAYPOINTS time_sec", waypoints, JOINT_WAYPOINT_TIME_SEC)
    estimated_time_for_speed_mode = estimate_speed_percent_duration(waypoints, SPEED_PERCENT)
    summarize_joint_path("JOINT_WAYPOINTS speed_percent estimated", waypoints, estimated_time_for_speed_mode)
    log().info("local preflight passed")
    flush_logs()


def estimate_speed_percent_duration(waypoints: np.ndarray, speed_percent: float) -> float:
    if not (0.0 < speed_percent <= 1.0):
        raise ValueError("SPEED_PERCENT must be in (0, 1]")
    max_vel_limits = load_limit_vector(
        "joint_trajectory",
        "max_vel_limits",
        [5.5, 5.5, 5.5, 20.9, 20.9, 20.9],
    )
    dq = np.abs(np.diff(waypoints, axis=0))
    per_segment_time = np.max(dq / np.maximum(max_vel_limits * speed_percent, 1e-9), axis=1)
    total = float(np.sum(per_segment_time))
    return max(total, 1e-6)


def main() -> None:
    global _logger
    _logger = setup_logging()
    install_signal_handlers()

    if os.environ.get(LOCAL_PREFLIGHT_ONLY_ENV, "0") == "1":
        run_local_preflight_only()
        return

    validate_joint_waypoints("JOINT_WAYPOINTS", JOINT_WAYPOINTS)
    validate_joint_waypoints("HOME_JOINTS", [HOME_JOINTS])
    validate_gripper_positions()

    arm = create_arm()
    set_active_arm(arm)

    try:
        restored_poses = restore_poses_from_joint_plan(arm)
        loop_index = 1
        max_loop_count = FULL_TEST_LOOP_COUNT if FULL_TEST_LOOP_COUNT > 0 else MAX_LOOP_COUNT_WHEN_NOT_FOREVER
        while RUN_FOREVER or loop_index <= max_loop_count:
            if _shutdown_requested.is_set():
                raise KeyboardInterrupt
            run_one_full_test_loop(arm, loop_index, restored_poses)
            loop_index += 1
    except KeyboardInterrupt:
        log().warning("interrupted by user")
        return_home_after_interrupt()
    except BaseException:  # noqa: BLE001
        log().exception("test stopped by error")
        cleanup_active_arm()
        raise
    finally:
        cleanup_active_arm()
        flush_logs()


if __name__ == "__main__":
    main()
