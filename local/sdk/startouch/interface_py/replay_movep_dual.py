import yaml
import os
import numpy as np
from pathlib import Path
import queue
import signal
import time
import threading
import traceback

from replay_refresh_utils import select_session_subdir, load_trajectory, transform_traj

try:
    from startouchclass import SingleArm
except Exception as e:
    pass

CONFIG_PATH = Path(__file__).with_name("replay_refresh_config.yaml")

MOVE_TO_ZERO_TIME_SEC = 3.0
MOVE_TO_TRAJECTORY_TIME_SEC = 3.0
TRAJECTORY_SETTLE_SEC = 1.0
MOVE_P_BLEND_RADIUS_M = 0.008
MOVE_P_POSITION_TOLERANCE_M = 0.01
MOVE_P_ORIENTATION_TOLERANCE_RAD = 0.015
MOVE_P_INTERVAL = 1
MOVE_P_CONTROL_HZ = 400.0
GRIPPER_SYNC_HZ = 200.0
ZERO_JOINTS = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
DEFAULT_DUAL_MULTI_SESSION_DIR = Path("/home/lumos/code/FastTouchV2/fnl/fnl/fastumi/DATA/multi_session_20260430")

_active_arms = []
_cleanup_started = threading.Event()
_shutdown_requested = threading.Event()
_return_home_started = threading.Event()


def request_shutdown(signum=None, frame=None):
    _shutdown_requested.set()
    print("\n收到中断信号，正在停止机械臂并退出...")
    raise KeyboardInterrupt


def cleanup_active_arms():
    if _cleanup_started.is_set():
        return
    _cleanup_started.set()
    for arm in _active_arms:
        try:
            arm.cleanup()
        except Exception:
            traceback.print_exc()


def return_dual_arms_to_zero_after_interrupt(left_can_port, right_can_port):
    if _return_home_started.is_set():
        return
    _return_home_started.set()
    print(
        "中断当前动作后左右臂回到0位: "
        f"left={left_can_port}, right={right_can_port}, time_sec={MOVE_TO_ZERO_TIME_SEC}"
    )
    cleanup_active_arms()
    time.sleep(0.2)
    home_arms = []
    try:
        left_home = SingleArm(can_interface_=left_can_port, gripper=True, enable_fd_=False)
        right_home = SingleArm(can_interface_=right_can_port, gripper=True, enable_fd_=False)
        home_arms = [left_home, right_home]

        errors = []

        def go_home(label, arm):
            try:
                arm.set_joint_waypoints([ZERO_JOINTS], time_sec=MOVE_TO_ZERO_TIME_SEC)
                arm.setGripperDistance(0.085)
            except BaseException as exc:  # noqa: BLE001
                errors.append((label, exc))

        threads = [
            threading.Thread(target=go_home, args=("left", left_home), daemon=True),
            threading.Thread(target=go_home, args=("right", right_home), daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        if errors:
            for label, exc in errors:
                print(f"{label} arm 回到0位失败: {exc}")
            print("回到0位未完全成功，请人工确认机械臂状态。")
        else:
            print("左右臂已回到0位。")
    except Exception:
        print("回到0位失败，请人工确认机械臂状态。")
        traceback.print_exc()
    finally:
        for arm in home_arms:
            try:
                arm.cleanup()
            except Exception:
                traceback.print_exc()


def run_interruptible_arm_call(call_fn, *args, **kwargs):
    result_queue = queue.Queue(maxsize=1)

    def target():
        try:
            result_queue.put((True, call_fn(*args, **kwargs)))
        except BaseException as e:
            result_queue.put((False, e))

    worker = threading.Thread(target=target, daemon=True)
    worker.start()

    try:
        while worker.is_alive():
            worker.join(timeout=0.1)
            if _shutdown_requested.is_set():
                cleanup_active_arms()
                raise KeyboardInterrupt
    except KeyboardInterrupt:
        _shutdown_requested.set()
        cleanup_active_arms()
        raise

    ok, value = result_queue.get()
    if ok:
        return value
    raise value


def move_joint_waypoints_interruptible(arm, waypoints, **kwargs):
    return run_interruptible_arm_call(arm.set_joint_waypoints, waypoints, **kwargs)


def move_p_interruptible(arm, poses, **kwargs):
    return run_interruptible_arm_call(arm.move_p, poses, **kwargs)


def clamp_width_to_distance(width):
    return float(np.clip(width / 1000.0, 0.0, 0.085))


def start_gripper_sync_thread(arm, timestamps, clamp_widths, motion_duration):
    stop_event = threading.Event()
    if len(clamp_widths) == 0:
        return stop_event, None

    command_period = 1.0 / GRIPPER_SYNC_HZ
    timestamps = np.asarray(timestamps, dtype=float)
    clamp_widths = np.asarray(clamp_widths, dtype=float)
    relative_timestamps = timestamps - timestamps[0]
    raw_duration = float(relative_timestamps[-1])
    if raw_duration <= 0.0:
        command_times = np.linspace(0.0, motion_duration, len(clamp_widths))
    else:
        command_times = relative_timestamps / raw_duration * motion_duration

    def sync_loop():
        start_time = time.monotonic()
        last_command_time = -command_period
        for command_time, width in zip(command_times, clamp_widths):
            if _shutdown_requested.is_set() or stop_event.is_set():
                break
            if command_time - last_command_time < command_period:
                continue
            wait_time = start_time + float(command_time) - time.monotonic()
            if wait_time > 0 and stop_event.wait(wait_time):
                break
            if _shutdown_requested.is_set() or stop_event.is_set():
                break
            try:
                arm.setGripperDistance(clamp_width_to_distance(width), 10, 0.5)
                last_command_time = command_time
            except Exception:
                traceback.print_exc()
                break

    thread = threading.Thread(target=sync_loop, daemon=True)
    thread.start()
    return stop_event, thread


def get_required_matrix(config_section, key, fallback=None):
    value = config_section.get(key, fallback)
    if value is None:
        raise KeyError(f"missing required config matrix: {key}")
    return np.array(value)


def select_dual_hand_dirs(multi_session_dir):
    session_dir = select_session_subdir(multi_session_dir)
    hand_dirs = sorted(
        [
            p for p in Path(session_dir).iterdir()
            if p.is_dir() and (p.name.startswith("left_hand_") or p.name.startswith("right_hand_"))
        ],
        key=lambda p: p.name,
    )
    if not hand_dirs:
        raise FileNotFoundError(f"在 '{session_dir}' 下未找到 left_hand_* 或 right_hand_* 目录。")
    left_dirs = [p for p in hand_dirs if p.name.startswith("left_hand_")]
    right_dirs = [p for p in hand_dirs if p.name.startswith("right_hand_")]
    if not left_dirs or not right_dirs:
        raise FileNotFoundError(f"在 '{session_dir}' 下需要同时存在 left_hand_* 和 right_hand_* 目录。")

    left_dir = left_dirs[0]
    right_dir = right_dirs[0]
    print(f"\n📂 当前子会话：{session_dir.name}")
    print(f"→ 左手数据目录：{left_dir.name}")
    print(f"→ 右手数据目录：{right_dir.name}")
    return left_dir, right_dir


def run_dual_replay(left_args, right_args):
    results = {}

    def target(name, args):
        try:
            results[name] = (True, replay_movep_with_original_timing(*args))
        except BaseException as e:
            results[name] = (False, e)

    threads = [
        threading.Thread(target=target, args=("left", left_args), daemon=True),
        threading.Thread(target=target, args=("right", right_args), daemon=True),
    ]
    for thread in threads:
        thread.start()

    try:
        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(timeout=0.1)
            if _shutdown_requested.is_set():
                cleanup_active_arms()
                raise KeyboardInterrupt
    except KeyboardInterrupt:
        _shutdown_requested.set()
        cleanup_active_arms()
        raise

    for name in ("left", "right"):
        ok, value = results[name]
        if not ok:
            raise RuntimeError(f"{name} arm replay failed") from value
    return results["left"][1], results["right"][1]


def print_pose_range(label, poses):
    pose_array = np.asarray(poses, dtype=float)
    xyz = pose_array[:, :3]
    print(
        f"{label} pose范围: "
        f"x=[{xyz[:, 0].min():.6f}, {xyz[:, 0].max():.6f}], "
        f"y=[{xyz[:, 1].min():.6f}, {xyz[:, 1].max():.6f}], "
        f"z=[{xyz[:, 2].min():.6f}, {xyz[:, 2].max():.6f}]"
    )


def solve_pose_to_joints(arm, pose, q_seed, label):
    q_sol, ok = arm.arm.solve_ik(
        list(np.asarray(pose[:3], dtype=float)),
        list(np.asarray(pose[3:6], dtype=float)),
        list(q_seed),
    )
    if not ok:
        raise RuntimeError(f"IK failed for {label}: pose={np.asarray(pose).tolist()}, seed={q_seed}")
    return list(q_sol)


def replay_movep_with_original_timing(
    arm,
    speed_rate,
    target_pose,
    target_clamp_width,
    pose_timestamps,
    initial_joints,
    interval=1,
    blend_radius_m=MOVE_P_BLEND_RADIUS_M,
    position_tolerance_m=MOVE_P_POSITION_TOLERANCE_M,
    orientation_tolerance_rad=MOVE_P_ORIENTATION_TOLERANCE_RAD,
):
    if speed_rate <= 0:
        raise ValueError("speed_rate must be > 0")
    if interval <= 0:
        raise ValueError("interval must be > 0")

    source_timestamps = np.asarray(pose_timestamps, dtype=float)
    source_pose = np.asarray(target_pose, dtype=float)
    source_clamp = np.asarray(target_clamp_width, dtype=float)
    if len(source_pose) == 0:
        raise ValueError("empty sampled trajectory")

    sampled_indices = list(range(0, len(source_pose), interval))
    if sampled_indices[-1] != len(source_pose) - 1:
        sampled_indices.append(len(source_pose) - 1)
    sampled_timestamps = source_timestamps[sampled_indices]
    sampled_pose = source_pose[sampled_indices]
    sampled_clamp = source_clamp[sampled_indices]

    timestamps = sampled_timestamps - sampled_timestamps[0]
    raw_total_time = float(timestamps[-1])
    total_time = raw_total_time / speed_rate
    if total_time <= 0.0:
        diffs = np.diff(sampled_timestamps)
        diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
        dt = float(np.median(diffs)) if len(diffs) else 0.01
        total_time = max((len(sampled_pose) - 1) * dt / speed_rate, dt / speed_rate)
    min_total_time = max((len(sampled_pose) - 1) / MOVE_P_CONTROL_HZ, 0.0)
    if total_time < min_total_time:
        print(
            f"执行时长 {total_time:.3f}s 小于 {len(sampled_pose) - 1} 段 "
            f"@ {MOVE_P_CONTROL_HZ:.0f}Hz 的最小时长 {min_total_time:.3f}s，自动延长。"
        )
        total_time = min_total_time

    print(
        f"开始 MoveP 轨迹复现 (interval={interval}): "
        f"原始pose点数={len(source_pose)}, 抽帧后pose点数={len(sampled_pose)}, "
        f"抽帧后原始时长: {raw_total_time:.2f} 秒, 执行时长: {total_time:.2f} 秒, "
        f"blend_radius_m={blend_radius_m}, "
        f"position_tolerance_m={position_tolerance_m}, "
        f"orientation_tolerance_rad={orientation_tolerance_rad}"
    )

    current_joints = np.asarray(arm.get_joint_positions(), dtype=float).tolist()
    print(f"当前关节位置: {current_joints}")
    print(f"current -> initial_joints, time_sec={MOVE_TO_ZERO_TIME_SEC}")
    move_joint_waypoints_interruptible(arm, [initial_joints], time_sec=MOVE_TO_ZERO_TIME_SEC)

    q_first = solve_pose_to_joints(arm, sampled_pose[0], initial_joints, "sampled_pose[0]")
    q_last = solve_pose_to_joints(arm, sampled_pose[-1], q_first, "sampled_pose[-1]")
    print(f"MoveP 起点IK: {q_first}")
    print(f"MoveP 终点IK: {q_last}")

    if len(sampled_clamp) > 0:
        arm.setGripperDistance(clamp_width_to_distance(sampled_clamp[0]), 10, 0.5)

    print(f"initial_joints -> sampled_pose[0], time_sec={MOVE_TO_TRAJECTORY_TIME_SEC}")
    move_joint_waypoints_interruptible(arm, [q_first], time_sec=MOVE_TO_TRAJECTORY_TIME_SEC)
    print(f"到达轨迹起点，停止 {TRAJECTORY_SETTLE_SEC}s")
    time.sleep(TRAJECTORY_SETTLE_SEC)

    if len(sampled_pose) == 1:
        print("轨迹只有 1 个采样点，跳过 MoveP。")
        motion_duration = 0.0
    else:
        gripper_stop_event, gripper_thread = start_gripper_sync_thread(
            arm,
            sampled_timestamps,
            sampled_clamp,
            total_time,
        )
        try:
            motion_duration = move_p_interruptible(
                arm,
                sampled_pose.tolist(),
                time_sec=total_time,
                blend_radius_m=blend_radius_m,
                position_tolerance_m=position_tolerance_m,
                orientation_tolerance_rad=orientation_tolerance_rad,
            )
        finally:
            gripper_stop_event.set()
            if gripper_thread is not None:
                gripper_thread.join(timeout=1.0)
        if len(sampled_clamp) > 0:
            arm.setGripperDistance(clamp_width_to_distance(sampled_clamp[-1]), 10, 0.5)
        print(f"MoveP 轨迹回放完成: planned_duration_s={motion_duration:.3f}")

    print(f"轨迹结束，停止 {TRAJECTORY_SETTLE_SEC}s")
    time.sleep(TRAJECTORY_SETTLE_SEC)
    print(f"sampled_pose[-1]/current -> initial_joints, time_sec={MOVE_TO_ZERO_TIME_SEC}")
    move_joint_waypoints_interruptible(arm, [initial_joints], time_sec=MOVE_TO_ZERO_TIME_SEC)
    return motion_duration


if __name__ == "__main__":  
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    # Load configuration
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
        print(config)

    if config["StarTouch"]["enable"]:
        speed_rate = config["speed_rate"]   
        dual_config = config.get("DualArm", config.get("DualStarTouch", {}))
        left_can_port = dual_config.get("left_can_port", "can0")
        right_can_port = dual_config.get("right_can_port", "can1")
        left_startouch = SingleArm(can_interface_=left_can_port, gripper=True, enable_fd_=False)
        right_startouch = SingleArm(can_interface_=right_can_port, gripper=True, enable_fd_=False)
        _active_arms.extend([left_startouch, right_startouch])
        time.sleep(2)
        left_current_joints = np.asarray(left_startouch.get_joint_positions(), dtype=float).tolist()
        right_current_joints = np.asarray(right_startouch.get_joint_positions(), dtype=float).tolist()
        print(f"初始化完成，左臂当前关节位置: {left_current_joints}")
        print(f"初始化完成，右臂当前关节位置: {right_current_joints}")

    # Replay loop: after each round, reselect from multi-session -> session.
    speed_rate = config["speed_rate"]
    initial_joints = config["initial_joints"]
    dual_multi_session_dir = Path(config.get("dual_multi_session_dir", DEFAULT_DUAL_MULTI_SESSION_DIR))
    time.sleep(1)
    try:
        while True:
            left_session, right_session = select_dual_hand_dirs(dual_multi_session_dir)
            left_clamp_path = os.path.join(left_session, "Clamp_Data", "clamp_data_tum.txt")
            left_traj_path = os.path.join(left_session, "Merged_Trajectory", "merged_trajectory.txt")
            right_clamp_path = os.path.join(right_session, "Clamp_Data", "clamp_data_tum.txt")
            right_traj_path = os.path.join(right_session, "Merged_Trajectory", "merged_trajectory.txt")

            left_raw_pose, left_raw_clamp, left_pose_timestamps = load_trajectory(left_traj_path, left_clamp_path)
            right_raw_pose, right_raw_clamp, right_pose_timestamps = load_trajectory(right_traj_path, right_clamp_path)
            print(
                f"已加载左臂轨迹: session={left_session}, "
                f"pose_rows={len(left_raw_pose)}, clamp_rows={len(left_raw_clamp)}, "
                f"speed_rate={speed_rate}, interval={MOVE_P_INTERVAL}"
            )
            print(
                f"已加载右臂轨迹: session={right_session}, "
                f"pose_rows={len(right_raw_pose)}, clamp_rows={len(right_raw_clamp)}, "
                f"speed_rate={speed_rate}, interval={MOVE_P_INTERVAL}"
            )
            if config["StarTouch"]["enable"]:
                dual_config = config.get("DualArm", config.get("DualStarTouch", {}))
                default_T_base2local = config.get("T_base2local", config["StarTouch"].get("T_base2local"))
                left_T_base2local = get_required_matrix(
                    dual_config,
                    "left_T_base2local",
                    default_T_base2local,
                )
                right_T_base2local = get_required_matrix(
                    dual_config,
                    "right_T_base2local",
                    default_T_base2local,
                )
                left_startouch_pose, left_startouch_clamp_width = transform_traj(
                    left_raw_pose,
                    left_raw_clamp,
                    left_pose_timestamps,
                    left_T_base2local
                )
                right_startouch_pose, right_startouch_clamp_width = transform_traj(
                    right_raw_pose,
                    right_raw_clamp,
                    right_pose_timestamps,
                    right_T_base2local
                )
                print_pose_range("左臂", left_startouch_pose)
                print_pose_range("右臂", right_startouch_pose)
                run_dual_replay(
                    (
                        left_startouch,
                        speed_rate,
                        left_startouch_pose,
                        left_startouch_clamp_width,
                        left_pose_timestamps,
                        initial_joints,
                        MOVE_P_INTERVAL,
                        MOVE_P_BLEND_RADIUS_M,
                        MOVE_P_POSITION_TOLERANCE_M,
                        MOVE_P_ORIENTATION_TOLERANCE_RAD,
                    ),
                    (
                        right_startouch,
                        speed_rate,
                        right_startouch_pose,
                        right_startouch_clamp_width,
                        right_pose_timestamps,
                        initial_joints,
                        MOVE_P_INTERVAL,
                        MOVE_P_BLEND_RADIUS_M,
                        MOVE_P_POSITION_TOLERANCE_M,
                        MOVE_P_ORIENTATION_TOLERANCE_RAD,
                    ),
                )
                left_startouch.setGripperDistance(0.085) # Ensure gripper is open before next replay.
                right_startouch.setGripperDistance(0.085)
                time.sleep(1)
                print("\n✅ 当前轨迹播放完成，可继续选择下一条轨迹（Ctrl+C 退出）。")
            else:
                print("⚠️ StarTouch 未启用，未执行轨迹回放。")
    except KeyboardInterrupt:
        print("\n⏹ 已退出轨迹回放选择。")
        if config["StarTouch"]["enable"]:
            return_dual_arms_to_zero_after_interrupt(left_can_port, right_can_port)
    except Exception as e:
        print(f"\n[ERROR] MoveP 轨迹回放失败: {e}")
        traceback.print_exc()
    finally:
        if config["StarTouch"]["enable"]:
            cleanup_active_arms()
