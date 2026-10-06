import ast
import math
import re
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from startouchclass import SingleArm, euler_to_quaternion
from tcp_compensation import flange_position_to_tcp, tcp_position_to_flange


CAN_INTERFACE = "can0"
ENABLE_FD = False

TRAJ_FILE = None
DEFAULT_TRAJ_DIR = Path("/home/lumos/code/FastTouchV2/fnl/fnl/vlareplay")
TRAJ_GLOB = "inferenceTraj_20260509_170209.txt"
# TRAJ_GLOB = "*209.txt"

# "cmd_flange" replays the cmd_pos/cmd_euler_rad fields written by
# pi0_rollout_single_startouch_lxh.py. "action_tcp" replays raw action xyz/rpy/g
# and applies the same TCP-to-flange conversion used by that rollout script.
REPLAY_POSE_SOURCE = "cmd_flange"
TCP_OFFSET_XYZ = [0.0, 0.0, 0.0]

# Joint waypoint action chunk replay:
# VLA pose chunk -> IK -> non-blocking joint waypoint chunk update with gripper.
EXECUTION_MODE = "joint_waypoint_chunk"

# "timesec": use explicit group duration. "speedpercent": use trajectory limits scaled by SPEED_PERCENT.
TIMING_MODE = "speedpercent"
GROUP_SIZE = 30
GROUP_BY_STEP_IDX_RESET = False
DEFAULT_GROUP_TIME_SEC = 4.0
GROUP_TIME_SECS = [
    3.0,
    12.0,
    4.0,
    4.0,
    5.0,
]
SPEED_PERCENT = 0.15
SWITCH_AFTER_POINTS_SEQUENCE = [3, 10, 20]
SWITCH_DELAY_SEC = 0.05

MOVE_TO_FIRST_POSE_USE_TIME_MODE = True
MOVE_TO_FIRST_POSE_TIME_SEC = 5.0
MOVE_TO_FIRST_POSE_SPEED_PERCENT = 1.0

ZERO_JOINTS = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
RETURN_HOME_TIME_SEC = 3.0
MAX_FRAMES = 0
LOW_Z_WARN_M = 0.06
LARGE_BOUNDARY_JUMP_WARN_M = 0.02

ENABLE_PLOT = True
FEEDBACK_SAMPLE_HZ = 200.0
PLOT_JOINT_OUT = Path("vla_replay_joint_waypoint_chunk_joint_cmd_vs_feedback.png")
PLOT_TOOL_OUT = Path("vla_replay_joint_waypoint_chunk_tool_cmd_vs_feedback.png")


@dataclass
class MotionResult:
    duration: float = 0.0
    error: Optional[BaseException] = None
    call_start_time: float = 0.0
    call_end_time: float = 0.0


class FeedbackRecorder:
    def __init__(self, arm, tcp_offset_xyz, sample_hz: float):
        self.arm = arm
        self.tcp_offset_xyz = np.asarray(tcp_offset_xyz, dtype=float)
        self.period = 1.0 / float(sample_hz)
        self.stop_event = threading.Event()
        self.records = []
        self.errors = []
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2.0)

    def _loop(self):
        while not self.stop_event.is_set():
            t0 = time.monotonic()
            try:
                q = np.asarray(self.arm.get_joint_positions(), dtype=float)
                flange_pos, quat_wxyz = self.arm.get_ee_pose_quat()
                _flange_pos_euler, flange_euler = self.arm.get_ee_pose_euler()
                tool_pos = flange_position_to_tcp(flange_pos, quat_wxyz, self.tcp_offset_xyz)
                gripper = float(self.arm.get_gripper_position())
                t1 = time.monotonic()
                self.records.append(
                    [
                        0.5 * (t0 + t1),
                        *q.tolist(),
                        *np.asarray(tool_pos, dtype=float).tolist(),
                        *np.asarray(flange_euler, dtype=float).tolist(),
                        gripper,
                    ]
                )
            except Exception as exc:  # noqa: BLE001
                self.errors.append((time.monotonic(), repr(exc)))
            elapsed = time.monotonic() - t0
            self.stop_event.wait(max(0.0, self.period - elapsed))

    def as_array(self):
        if not self.records:
            return np.empty((0, 14), dtype=float)
        return np.asarray(self.records, dtype=float)


def action_to_flange_frame(action_values, tcp_offset_xyz):
    if len(action_values) < 7:
        raise ValueError(f"action must contain 7 values, got {len(action_values)}")
    x, y, z, roll_deg, pitch_deg, yaw_deg, gripper = [float(v) for v in action_values[:7]]
    euler_rad = [
        math.radians(roll_deg),
        math.radians(pitch_deg),
        math.radians(yaw_deg),
    ]
    flange_pos = tcp_position_to_flange([x, y, z], euler_rad, tcp_offset_xyz).tolist()
    return [
        flange_pos[0],
        flange_pos[1],
        flange_pos[2],
        euler_rad[0],
        euler_rad[1],
        euler_rad[2],
        float(min(1.0, max(0.0, gripper))),
    ]


def parse_traj(path: Path):
    cmd_pattern = re.compile(
        r"(?:cmdpos|cmd_pos)=(\[[^\]]+\])\s+"
        r"(?:cmdeulerrad|cmd_euler_rad)=(\[[^\]]+\])\s+"
        r"(?:cmdgripper|cmd_gripper)=([-\d.eE]+)"
    )
    action_pattern = re.compile(r"action=(\[[^\]]+\])")
    step_pattern = re.compile(r"(?:stepidx|step_idx)=(-?\d+)")
    frames = []
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        step_match = step_pattern.search(line)
        step_idx = int(step_match.group(1)) if step_match else None
        if REPLAY_POSE_SOURCE == "cmd_flange":
            match = cmd_pattern.search(line)
            if not match:
                continue
            pos = ast.literal_eval(match.group(1))
            euler = ast.literal_eval(match.group(2))
            gripper = float(match.group(3))
            if len(pos) != 3 or len(euler) != 3:
                raise RuntimeError(f"bad frame at line {line_no}: pos/euler must be length 3")
            frame = [
                float(pos[0]),
                float(pos[1]),
                float(pos[2]),
                float(euler[0]),
                float(euler[1]),
                float(euler[2]),
                float(gripper),
            ]
        elif REPLAY_POSE_SOURCE == "action_tcp":
            match = action_pattern.search(line)
            if not match:
                continue
            frame = action_to_flange_frame(ast.literal_eval(match.group(1)), TCP_OFFSET_XYZ)
        else:
            raise ValueError("REPLAY_POSE_SOURCE must be 'cmd_flange' or 'action_tcp'")
        frames.append((step_idx, frame))
    return frames


def resolve_traj_file() -> Path:
    if TRAJ_FILE is not None:
        return Path(TRAJ_FILE)
    candidates = sorted(DEFAULT_TRAJ_DIR.glob(TRAJ_GLOB))
    if not candidates:
        raise FileNotFoundError(f"no trajectory files matched {DEFAULT_TRAJ_DIR / TRAJ_GLOB}")
    return candidates[-1]


def frame_groups(entries, group_size):
    if GROUP_BY_STEP_IDX_RESET and any(step_idx is not None for step_idx, _frame in entries):
        group_start = 0
        group = []
        for row_idx, (step_idx, frame) in enumerate(entries):
            if step_idx == 0 and group:
                yield group_start, group
                group_start = row_idx
                group = []
            group.append(frame)
        if group:
            yield group_start, group
        return

    frames = [frame for _step_idx, frame in entries]
    for start in range(0, len(frames), group_size):
        yield start, frames[start:start + group_size]


def print_data_diagnostics(entries, groups):
    frames = [frame for _step_idx, frame in entries]
    if not frames:
        return
    z_values = [frame[2] for frame in frames]
    print(f"z range: min={min(z_values):.4f}m, max={max(z_values):.4f}m")
    if min(z_values) < LOW_Z_WARN_M:
        print(
            "WARNING: trajectory contains low-z Cartesian targets; "
            "move_p may reject or shake if these poses are outside the reachable workspace."
        )

    for group_idx, (start, group) in enumerate(groups, 1):
        group_z = [frame[2] for frame in group]
        print(
            f"group {group_idx}: rows {start}..{start + len(group) - 1}, "
            f"points={len(group)}, z_min={min(group_z):.4f}, z_max={max(group_z):.4f}"
        )

    for i in range(1, len(frames)):
        prev_frame = frames[i - 1]
        frame = frames[i]
        jump = math.sqrt(sum((frame[j] - prev_frame[j]) ** 2 for j in range(3)))
        if jump > LARGE_BOUNDARY_JUMP_WARN_M:
            print(
                f"WARNING: large Cartesian jump at rows {i - 1}->{i}: "
                f"{jump:.4f}m, z {prev_frame[2]:.4f}->{frame[2]:.4f}"
            )


def solve_joint_waypoints(arm, frames):
    q_seed = list(arm.get_joint_positions())
    joint_points = []
    for idx, frame in enumerate(frames):
        quat_wxyz = euler_to_quaternion(frame[3], frame[4], frame[5])
        q, ok = arm.solve_ik(frame[:3], quat_wxyz, q_seed=q_seed)
        if not ok:
            raise RuntimeError(f"IK failed at frame {idx}: pos={frame[:3]}, euler={frame[3:6]}")
        q_seed = list(q)
        joint_points.append(q_seed)
    return joint_points


def require_replay_interfaces(arm):
    required = [
        "update_joint_waypoint_chunk_with_gripper",
        "get_last_waypoint_command_samples",
    ]
    missing = [name for name in required if not hasattr(arm.arm, name)]
    if missing:
        raise RuntimeError(
            "startouch pybind is missing required synchronized replay interface(s): "
            + ", ".join(missing)
        )


def command_samples_to_array(arm, motion_result: MotionResult, tcp_offset_xyz):
    rows = arm.get_last_waypoint_command_samples()
    if not rows:
        return np.empty((0, 15), dtype=float)
    arr = np.asarray(rows, dtype=float)
    if arr.ndim != 2 or arr.shape[1] < 15:
        raise RuntimeError(f"bad command sample shape: {arr.shape}")
    # Chunk update is non-blocking: the command samples are relative to the newly
    # installed chunk trajectory, so use the update call return time as the Python clock anchor.
    motion_start = motion_result.call_end_time
    out = arr[:, :15].copy()
    out[:, 0] = motion_start + arr[:, 0]
    tcp_offset_xyz = np.asarray(tcp_offset_xyz, dtype=float)
    for idx in range(out.shape[0]):
        flange_pos = out[idx, 7:10]
        euler_rad = out[idx, 10:13]
        quat_wxyz = euler_to_quaternion(euler_rad[0], euler_rad[1], euler_rad[2])
        out[idx, 7:10] = flange_position_to_tcp(flange_pos, quat_wxyz, tcp_offset_xyz)
    return out


def frame_to_tool_pose(frame, tcp_offset_xyz):
    flange_pos = np.asarray(frame[:3], dtype=float)
    euler_rad = np.asarray(frame[3:6], dtype=float)
    quat_wxyz = euler_to_quaternion(euler_rad[0], euler_rad[1], euler_rad[2])
    tool_pos = flange_position_to_tcp(flange_pos, quat_wxyz, np.asarray(tcp_offset_xyz, dtype=float))
    return np.asarray([*tool_pos, *euler_rad.tolist()], dtype=float)


def _nearest_monotonic_indices(reference_values, target_values):
    if len(reference_values) == 0 or len(target_values) == 0:
        return np.empty((0,), dtype=int)
    indices = []
    start = 0
    for target in target_values:
        window = reference_values[start:]
        if len(window) == 0:
            indices.append(len(reference_values) - 1)
            continue
        local_idx = int(np.argmin(np.linalg.norm(window - target, axis=1)))
        idx = start + local_idx
        indices.append(idx)
        start = min(idx + 1, len(reference_values) - 1)
    return np.asarray(indices, dtype=int)


def original_cmd_points_to_array(group, command_arr, execution_mode, tcp_offset_xyz, joint_points=None):
    if command_arr.size == 0:
        return {"t": np.empty((0,), dtype=float), "joint": np.empty((0, 6)), "tool": np.empty((0, 6))}

    tool_points = np.asarray(
        [frame_to_tool_pose(frame, tcp_offset_xyz) for frame in group],
        dtype=float,
    )
    if execution_mode in ("setjointwaypointwithgripper", "joint_waypoint_chunk"):
        joint_points = np.asarray(joint_points, dtype=float)
        indices = _nearest_monotonic_indices(command_arr[:, 1:7], joint_points)
        joint_markers = joint_points
    else:
        indices = _nearest_monotonic_indices(command_arr[:, 7:13], tool_points)
        joint_markers = command_arr[indices, 1:7]

    return {
        "t": command_arr[indices, 0],
        "joint": joint_markers,
        "tool": tool_points,
    }


def trim_command_array(command_arr, t_end=None):
    if command_arr.size == 0 or t_end is None:
        return command_arr
    return command_arr[command_arr[:, 0] <= float(t_end)]


def trim_marker_array(marker_arr, t_end=None):
    if t_end is None or len(marker_arr["t"]) == 0:
        return marker_arr
    mask = marker_arr["t"] <= float(t_end)
    return {
        "t": marker_arr["t"][mask],
        "joint": marker_arr["joint"][mask],
        "tool": marker_arr["tool"][mask],
    }


def select_switch_time(marker_arr, switch_after_points):
    if len(marker_arr["t"]) == 0:
        return None
    idx = min(max(1, int(switch_after_points)), len(marker_arr["t"])) - 1
    return float(marker_arr["t"][idx])


def _interp_columns(src_t, src_values, dst_t):
    result = np.empty((len(dst_t), src_values.shape[1]), dtype=float)
    for idx in range(src_values.shape[1]):
        result[:, idx] = np.interp(dst_t, src_t, src_values[:, idx])
    return result


def _plot_cmd_feedback(
    cmd_t,
    cmd_values,
    fb_t,
    fb_values,
    labels,
    ylabel,
    title,
    save_path: Path,
    marker_t=None,
    marker_values=None,
):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if len(cmd_t) < 2 or len(fb_t) < 2:
        print(f"skip plot {save_path}: not enough samples")
        return
    t0 = max(float(cmd_t[0]), float(fb_t[0]))
    t1 = min(float(cmd_t[-1]), float(fb_t[-1]))
    mask = (fb_t >= t0) & (fb_t <= t1)
    if int(mask.sum()) < 2:
        print(f"skip plot {save_path}: no overlapping time range")
        return
    t = fb_t[mask]
    fb = fb_values[mask]
    cmd = _interp_columns(cmd_t, cmd_values, t)
    err = fb - cmd
    x = t - t[0]

    fig, axes = plt.subplots(len(labels), 1, figsize=(12, 2.3 * len(labels)), sharex=True)
    axes = np.atleast_1d(axes)
    for idx, ax in enumerate(axes):
        cmd_line = ax.plot(x, cmd[:, idx], color="tab:blue", linewidth=1.2, label="cmd")[0]
        ax.plot(x, fb[:, idx], color="tab:orange", linewidth=1.0, linestyle="--", label="feedback")
        ax_right = ax.twinx()
        err_line = ax_right.plot(
            x,
            err[:, idx],
            color="tab:red",
            linewidth=0.8,
            alpha=0.75,
            label="error",
        )[0]
        if marker_t is not None and marker_values is not None and len(marker_t) > 0:
            marker_t_arr = np.asarray(marker_t, dtype=float)
            marker_values_arr = np.asarray(marker_values, dtype=float)
            marker_mask = (marker_t_arr >= t0) & (marker_t_arr <= t1)
            if np.any(marker_mask):
                marker_x = marker_t_arr[marker_mask] - t[0]
                marker_y = marker_values_arr[marker_mask, idx]
                ax.scatter(
                    marker_x,
                    marker_y,
                    s=14,
                    marker="o",
                    facecolors="white",
                    edgecolors="tab:blue",
                    linewidths=0.8,
                    zorder=4,
                    label="cmd raw point",
                )
        ax.set_ylabel(f"{labels[idx]}\n{ylabel}")
        ax_right.set_ylabel("error")
        err_abs = float(np.nanmax(np.abs(err[:, idx]))) if len(err) else 0.0
        if math.isfinite(err_abs) and err_abs > 0.0:
            ax_right.set_ylim(-err_abs * 1.2, err_abs * 1.2)
        ax.grid(True, alpha=0.25)
        if idx == 0:
            ax.set_title(title)
            handles, names = ax.get_legend_handles_labels()
            handles.append(err_line)
            names.append(err_line.get_label())
            ax.legend(handles, names, loc="best", fontsize=8, ncol=4)
        ax_right.tick_params(axis="y", labelcolor="tab:red")
    axes[-1].set_xlabel("time since overlap start (s)")
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print(f"saved plot: {save_path}")


def save_replay_plots(command_arrays, feedback_recorder: FeedbackRecorder, marker_arrays):
    if not ENABLE_PLOT:
        return
    feedback = feedback_recorder.as_array()
    command = np.vstack([arr for arr in command_arrays if arr.size > 0]) if command_arrays else np.empty((0, 15))
    if command.shape[0] < 2 or feedback.shape[0] < 2:
        print("skip plots: not enough command or feedback samples")
        return

    cmd_t = command[:, 0]
    cmd_joint = command[:, 1:7]
    cmd_tool = command[:, 7:13]
    fb_t = feedback[:, 0]
    fb_joint = feedback[:, 1:7]
    fb_tool = feedback[:, 7:13]
    marker_t = (
        np.concatenate([item["t"] for item in marker_arrays if len(item["t"]) > 0])
        if marker_arrays else np.empty((0,), dtype=float)
    )
    marker_joint = (
        np.vstack([item["joint"] for item in marker_arrays if len(item["t"]) > 0])
        if marker_arrays else np.empty((0, 6), dtype=float)
    )
    marker_tool = (
        np.vstack([item["tool"] for item in marker_arrays if len(item["t"]) > 0])
        if marker_arrays else np.empty((0, 6), dtype=float)
    )

    _plot_cmd_feedback(
        cmd_t,
        cmd_joint,
        fb_t,
        fb_joint,
        labels=[f"J{i}" for i in range(1, 7)],
        ylabel="rad",
        title="Joint CMD vs feedback",
        save_path=PLOT_JOINT_OUT,
        marker_t=marker_t,
        marker_values=marker_joint,
    )
    _plot_cmd_feedback(
        cmd_t,
        cmd_tool,
        fb_t,
        fb_tool,
        labels=["X", "Y", "Z", "Roll", "Pitch", "Yaw"],
        ylabel="m/rad",
        title="TOOL pose CMD vs feedback",
        save_path=PLOT_TOOL_OUT,
        marker_t=marker_t,
        marker_values=marker_tool,
    )


def run_joint_waypoint_chunk_update_with_gripper(arm, joint_points, gripper_positions, time_sec, speed_percent):
    return arm.update_joint_waypoint_chunk_with_gripper(
        joint_points,
        gripper_positions,
        time_sec=time_sec,
        speed_percent=speed_percent,
        switch_delay_sec=SWITCH_DELAY_SEC,
    )


def run_motion_thread(call_fn, *args, **kwargs):
    result = MotionResult()

    def worker():
        try:
            result.call_start_time = time.monotonic()
            result.duration = call_fn(*args, **kwargs)
            result.call_end_time = time.monotonic()
        except BaseException as exc:  # noqa: BLE001
            result.call_end_time = time.monotonic()
            result.error = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread, result


def wait_motion(thread, result, stop_requested):
    while thread.is_alive():
        thread.join(timeout=0.05)
        if stop_requested.is_set():
            thread.join(timeout=2.0)
            raise KeyboardInterrupt
    if result.error is not None:
        raise result.error
    return result.duration


def interruptible_sleep(seconds, stop_requested):
    deadline = time.monotonic() + max(0.0, float(seconds))
    while not stop_requested.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return
        time.sleep(min(0.05, remaining))
    raise KeyboardInterrupt


def return_home_after_interrupt(arm):
    print("Returning to zero joint position before exit.")
    arm.set_joint_waypoints([ZERO_JOINTS], time_sec=RETURN_HOME_TIME_SEC)


def group_time_sec(group_idx):
    idx = group_idx - 1
    if 0 <= idx < len(GROUP_TIME_SECS):
        return float(GROUP_TIME_SECS[idx])
    return float(DEFAULT_GROUP_TIME_SEC)


def main():
    if GROUP_SIZE <= 0:
        raise ValueError("GROUP_SIZE must be positive")
    use_time_mode = TIMING_MODE == "timesec"
    if TIMING_MODE not in ("timesec", "speedpercent"):
        raise ValueError("TIMING_MODE must be 'timesec' or 'speedpercent'")
    if use_time_mode and any(group_time_sec(i + 1) <= 0.0 for i in range(max(1, len(GROUP_TIME_SECS)))):
        raise ValueError("all group time values must be positive in time mode")
    if MOVE_TO_FIRST_POSE_USE_TIME_MODE and MOVE_TO_FIRST_POSE_TIME_SEC <= 0.0:
        raise ValueError("MOVE_TO_FIRST_POSE_TIME_SEC must be positive")
    if not MOVE_TO_FIRST_POSE_USE_TIME_MODE and not (0.0 < MOVE_TO_FIRST_POSE_SPEED_PERCENT <= 1.0):
        raise ValueError("MOVE_TO_FIRST_POSE_SPEED_PERCENT must be in (0, 1] in speed mode")
    if not use_time_mode and not (0.0 < SPEED_PERCENT <= 1.0):
        raise ValueError("SPEED_PERCENT must be in (0, 1] in speed mode")
    if not SWITCH_AFTER_POINTS_SEQUENCE:
        raise ValueError("SWITCH_AFTER_POINTS_SEQUENCE must not be empty")
    if any(int(value) <= 0 for value in SWITCH_AFTER_POINTS_SEQUENCE):
        raise ValueError("all switch point counts must be positive")
    if SWITCH_DELAY_SEC < 0.0:
        raise ValueError("SWITCH_DELAY_SEC must be non-negative")

    stop_requested = threading.Event()
    cleanup_started = threading.Event()

    def request_stop(signum, frame):  # noqa: ARG001
        stop_requested.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    traj_file = resolve_traj_file()
    frames = parse_traj(traj_file)
    if MAX_FRAMES > 0:
        frames = frames[:MAX_FRAMES]
    if not frames:
        raise RuntimeError(f"no cmdpos/cmdeulerrad/cmdgripper frames found in {traj_file}")

    print(f"using trajectory: {traj_file}")
    print(f"frames: {len(frames)}, group_size={GROUP_SIZE}")
    print(f"grouping: {'step_idx reset' if GROUP_BY_STEP_IDX_RESET else 'fixed row count'}")
    print(f"pose source: {REPLAY_POSE_SOURCE}, tcp_offset_xyz={TCP_OFFSET_XYZ}")
    if use_time_mode:
        print(f"mode: time, default_group_time_sec={DEFAULT_GROUP_TIME_SEC}, group_time_secs={GROUP_TIME_SECS}")
    else:
        print(f"mode: speed, speed_percent={SPEED_PERCENT}")
    print(f"execution mode: {EXECUTION_MODE}")
    print(f"switch_after_points_sequence={SWITCH_AFTER_POINTS_SEQUENCE}, switch_delay_sec={SWITCH_DELAY_SEC}")
    print("gripper replay: enabled")

    arm = SingleArm(can_interface_=CAN_INTERFACE, enable_fd_=ENABLE_FD)
    require_replay_interfaces(arm)
    feedback_recorder = None

    def cleanup_once():
        if cleanup_started.is_set():
            return
        cleanup_started.set()
        arm.cleanup()

    try:
        groups = list(frame_groups(frames, GROUP_SIZE))
        print_data_diagnostics(frames, groups)
        total_groups = len(groups)
        first_pose = groups[0][1][0][:6]
        current_pos, current_euler = arm.get_ee_pose_euler()
        current_pose = list(current_pos) + list(current_euler)
        print(f"current pose: {current_pose}")
        if MOVE_TO_FIRST_POSE_USE_TIME_MODE:
            print(f"move current pose -> first trajectory pose, time_sec={MOVE_TO_FIRST_POSE_TIME_SEC}")
            thread, result = run_motion_thread(
                arm.move_p,
                [current_pose, first_pose],
                time_sec=MOVE_TO_FIRST_POSE_TIME_SEC,
                blend_radius_m=0.0,
            )
        else:
            print(
                "move current pose -> first trajectory pose, "
                f"speed_percent={MOVE_TO_FIRST_POSE_SPEED_PERCENT}"
            )
            thread, result = run_motion_thread(
                arm.move_p,
                [current_pose, first_pose],
                speed_percent=MOVE_TO_FIRST_POSE_SPEED_PERCENT,
                blend_radius_m=0.0,
            )
        wait_motion(thread, result, stop_requested)

        command_arrays = []
        marker_arrays = []
        feedback_recorder = FeedbackRecorder(arm, TCP_OFFSET_XYZ, FEEDBACK_SAMPLE_HZ)
        feedback_recorder.start()

        for group_idx, (start, group) in enumerate(groups, 1):
            if stop_requested.is_set():
                raise KeyboardInterrupt
            end = start + len(group) - 1
            print(f"update chunk {group_idx}/{total_groups}: rows {start}..{end}, points={len(group)}")
            joint_points = solve_joint_waypoints(arm, group)
            if use_time_mode:
                this_group_time_sec = group_time_sec(group_idx)
                print(f"chunk {group_idx} time_sec={this_group_time_sec}")
                thread, result = run_motion_thread(
                    run_joint_waypoint_chunk_update_with_gripper,
                    arm,
                    joint_points,
                    [frame[6] for frame in group],
                    this_group_time_sec,
                    None,
                )
            else:
                thread, result = run_motion_thread(
                    run_joint_waypoint_chunk_update_with_gripper,
                    arm,
                    joint_points,
                    [frame[6] for frame in group],
                    None,
                    SPEED_PERCENT,
                )
            duration = wait_motion(thread, result, stop_requested)
            cmd_arr = command_samples_to_array(arm, result, TCP_OFFSET_XYZ)
            marker_arr = None
            if cmd_arr.size > 0:
                marker_arr = original_cmd_points_to_array(
                    group,
                    cmd_arr,
                    EXECUTION_MODE,
                    TCP_OFFSET_XYZ,
                    joint_points=joint_points,
                )
            print(f"chunk {group_idx} installed, planned_duration_s={duration:.3f}")

            if group_idx < total_groups and cmd_arr.size > 0 and marker_arr is not None:
                switch_after = SWITCH_AFTER_POINTS_SEQUENCE[(group_idx - 1) % len(SWITCH_AFTER_POINTS_SEQUENCE)]
                switch_time = select_switch_time(marker_arr, switch_after)
                if switch_time is None:
                    switch_time = time.monotonic() + max(0.0, min(duration, SWITCH_DELAY_SEC))
                command_arrays.append(trim_command_array(cmd_arr, switch_time))
                marker_arrays.append(trim_marker_array(marker_arr, switch_time))
                wait_sec = max(0.0, switch_time - time.monotonic())
                print(
                    f"wait until chunk {group_idx} reaches raw point {switch_after}; "
                    f"next update in {wait_sec:.3f}s"
                )
                interruptible_sleep(wait_sec, stop_requested)
            else:
                if cmd_arr.size > 0:
                    command_arrays.append(cmd_arr)
                    if marker_arr is not None:
                        marker_arrays.append(marker_arr)
                    final_wait = max(0.0, float(cmd_arr[-1, 0]) - time.monotonic())
                else:
                    final_wait = max(0.0, duration)
                print(f"final chunk installed; wait remaining motion {final_wait:.3f}s")
                interruptible_sleep(final_wait, stop_requested)
        feedback_recorder.stop()
        if feedback_recorder.errors:
            print(f"feedback recorder errors: {len(feedback_recorder.errors)}; first={feedback_recorder.errors[0]}")
        save_replay_plots(command_arrays, feedback_recorder, marker_arrays)
    except KeyboardInterrupt:
        print("Interrupted. Overriding current motion and returning to zero position.")
        return_home_after_interrupt(arm)
    finally:
        if feedback_recorder is not None:
            try:
                feedback_recorder.stop()
            except Exception:
                pass
        cleanup_once()


if __name__ == "__main__":
    main()
