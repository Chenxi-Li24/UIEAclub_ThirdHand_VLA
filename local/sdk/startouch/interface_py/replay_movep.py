import yaml
import os
import numpy as np
from pathlib import Path
import queue
import signal
import time
import threading
import traceback

from replay_refresh_utils import select_multi_sessions_dir, select_session_subdir, load_trajectory, transform_traj

try:
    from startouchclass import SingleArm
except Exception as e:
    pass

CONFIG_PATH = Path(__file__).with_name("replay_refresh_config.yaml")

MOVE_TO_ZERO_TIME_SEC = 3.0
MOVE_TO_TRAJECTORY_TIME_SEC = 3.0
TRAJECTORY_SETTLE_SEC = 1.0
MOVE_P_BLEND_RADIUS_M = 0.005
MOVE_P_POSITION_TOLERANCE_M = 0.005
MOVE_P_ORIENTATION_TOLERANCE_RAD = 0.008
MOVE_P_INTERVAL = 1
MOVE_P_CONTROL_HZ = 400.0
GRIPPER_SYNC_HZ = 50.0
ZERO_JOINTS = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

_active_arm = None
_cleanup_started = threading.Event()
_shutdown_requested = threading.Event()
_return_home_started = threading.Event()


def request_shutdown(signum=None, frame=None):
    _shutdown_requested.set()
    print("\n收到中断信号，正在停止机械臂并退出...")
    raise KeyboardInterrupt


def cleanup_active_arm():
    global _active_arm
    if _active_arm is None or _cleanup_started.is_set():
        return
    _cleanup_started.set()
    try:
        _active_arm.cleanup()
    except Exception:
        traceback.print_exc()


def return_arm_to_zero_after_interrupt(can_port):
    if _return_home_started.is_set():
        return
    _return_home_started.set()
    print(f"中断当前动作后回到0位: can={can_port}, time_sec={MOVE_TO_ZERO_TIME_SEC}")
    cleanup_active_arm()
    time.sleep(0.2)
    home_arm = None
    try:
        home_arm = SingleArm(can_interface_=can_port, gripper=True, enable_fd_=False)
        home_arm.set_joint_waypoints([ZERO_JOINTS], time_sec=MOVE_TO_ZERO_TIME_SEC)
        home_arm.setGripperDistance(0.085)
        print("已回到0位。")
    except Exception:
        print("回到0位失败，请人工确认机械臂状态。")
        traceback.print_exc()
    finally:
        if home_arm is not None:
            try:
                home_arm.cleanup()
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
                cleanup_active_arm()
                raise KeyboardInterrupt
    except KeyboardInterrupt:
        _shutdown_requested.set()
        cleanup_active_arm()
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

    current_joints = list(np.asarray(arm.get_joint_positions(), dtype=float))
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
        single_config = config.get("SingleArm", config["StarTouch"])
        can_port = single_config.get("single_port", single_config.get("can_port", "can0"))
        startouch = SingleArm(can_interface_=can_port, gripper=True, enable_fd_=False)#change false to true for fd, but currently fd has some issues, so set it to false.
        _active_arm = startouch
        time.sleep(2)
        current_joints = list(np.asarray(startouch.get_joint_positions(), dtype=float))
        print(f"初始化完成，当前关节位置: {current_joints}")

    # Replay loop: after each round, reselect from multi-session -> session.
    speed_rate = config["speed_rate"]
    initial_joints = config["initial_joints"]
    time.sleep(1)
    try:
        while True:
            multi_session_dir = select_multi_sessions_dir(base_path=config["DATA_ROOT"])
            selected_session = select_session_subdir(multi_session_dir)
            clamp_path = os.path.join(selected_session, "Clamp_Data", "clamp_data_tum.txt")
            traj_path = os.path.join(selected_session, "Merged_Trajectory", "merged_trajectory.txt")

            raw_pose, raw_clamp, pose_timestamps = load_trajectory(traj_path, clamp_path)
            print(
                f"已加载轨迹: session={selected_session}, "
                f"pose_rows={len(raw_pose)}, clamp_rows={len(raw_clamp)}, "
                f"speed_rate={speed_rate}, interval={MOVE_P_INTERVAL}"
            )
            if config["StarTouch"]["enable"]:
                single_config = config.get("SingleArm", config["StarTouch"])
                T_base2local = get_required_matrix(
                    single_config,
                    "T_base2local",
                    config.get("T_base2local", config["StarTouch"].get("T_base2local")),
                )
                startouch_pose, startouch_clamp_width = transform_traj(
                    raw_pose,
                    raw_clamp,
                    pose_timestamps,
                    T_base2local
                )
                # Keep replay.py's data loading, selection, speed_rate and interval semantics.
                # Only replace per-pose interpolation/raw command streaming with MoveP.
                replay_movep_with_original_timing(
                    startouch,
                    speed_rate,
                    startouch_pose,
                    startouch_clamp_width,
                    pose_timestamps,
                    initial_joints,
                    interval=MOVE_P_INTERVAL,
                    blend_radius_m=MOVE_P_BLEND_RADIUS_M,
                    position_tolerance_m=MOVE_P_POSITION_TOLERANCE_M,
                    orientation_tolerance_rad=MOVE_P_ORIENTATION_TOLERANCE_RAD,
                )
                startouch.setGripperDistance(0.085) # Ensure gripper is open before next replay.
                time.sleep(1)
                print("\n✅ 当前轨迹播放完成，可继续选择下一条轨迹（Ctrl+C 退出）。")
            else:
                print("⚠️ StarTouch 未启用，未执行轨迹回放。")
    except KeyboardInterrupt:
        print("\n⏹ 已退出轨迹回放选择。")
        if config["StarTouch"]["enable"]:
            return_arm_to_zero_after_interrupt(can_port)
    except Exception as e:
        print(f"\n[ERROR] MoveP 轨迹回放失败: {e}")
        traceback.print_exc()
    finally:
        if config["StarTouch"]["enable"]:
            cleanup_active_arm()
