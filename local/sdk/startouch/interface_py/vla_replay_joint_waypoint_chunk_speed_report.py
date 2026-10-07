import numpy as np

from startouchclass import SingleArm, euler_to_quaternion
from vla_replay_joint_waypoint_chunk import (
    CAN_INTERFACE,
    ENABLE_FD,
    GROUP_SIZE,
    SPEED_PERCENT,
    SWITCH_AFTER_POINTS_SEQUENCE,
    TIMING_MODE,
    frame_groups,
    group_time_sec,
    original_cmd_points_to_array,
    parse_traj,
    resolve_traj_file,
    select_switch_time,
)


CONTROL_HZ = 400.0
ZERO_SEED = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def solve_joint_waypoints_from_seed(arm, frames, q_seed):
    joint_points = []
    seed = list(q_seed)
    for idx, frame in enumerate(frames):
        quat_wxyz = euler_to_quaternion(frame[3], frame[4], frame[5])
        q, ok = arm.solve_ik(frame[:3], quat_wxyz, q_seed=seed)
        if not ok:
            raise RuntimeError(f"IK failed at frame {idx}: pos={frame[:3]}, euler={frame[3:6]}")
        seed = list(q)
        joint_points.append(seed)
    return joint_points


def plan_group(arm, q_start, joint_points, gripper, group_idx):
    if TIMING_MODE == "timesec":
        return np.asarray(
            arm.plan_joint_waypoints_with_gripper(
                q_start,
                joint_points,
                gripper,
                time_sec=group_time_sec(group_idx),
            ),
            dtype=float,
        )
    return np.asarray(
        arm.plan_joint_waypoints_with_gripper(
            q_start,
            joint_points,
            gripper,
            speed_percent=SPEED_PERCENT,
        ),
        dtype=float,
    )


def nearest_raw_point(marker_times, sample_time):
    if len(marker_times) == 0:
        return 0
    idx = int(np.searchsorted(marker_times, sample_time, side="right"))
    return max(0, min(idx, len(marker_times) - 1))


def report():
    traj_file = resolve_traj_file()
    entries = parse_traj(traj_file)
    groups = list(frame_groups(entries, GROUP_SIZE))
    arm = SingleArm(can_interface_=CAN_INTERFACE, enable_fd_=ENABLE_FD, gripper=True, dry_run=True)
    try:
        q_start = solve_joint_waypoints_from_seed(arm, [groups[0][1][0]], ZERO_SEED)[0]
        rows = []
        for group_idx, (row_start, group) in enumerate(groups, 1):
            joint_points = solve_joint_waypoints_from_seed(arm, group, q_start)
            gripper = [frame[6] for frame in group]
            planned = plan_group(arm, q_start, joint_points, gripper, group_idx)
            q_samples = planned[:, 1:7]
            vel = np.diff(q_samples, axis=0) * CONTROL_HZ
            abs_vel = np.abs(vel)
            max_per_joint = abs_vel.max(axis=0) if len(abs_vel) else np.zeros(6)
            peak_joint = int(max_per_joint.argmax())
            peak_sample = int(abs_vel[:, peak_joint].argmax()) if len(abs_vel) else 0
            peak_time = peak_sample / CONTROL_HZ

            marker = original_cmd_points_to_array(
                group,
                planned,
                "joint_waypoint_chunk",
                [0.0, 0.0, 0.0],
                joint_points=joint_points,
            )
            raw_idx = nearest_raw_point(marker["t"], peak_time)
            raw_row = row_start + raw_idx

            raw_path = np.vstack([np.asarray(q_start, dtype=float), np.asarray(joint_points, dtype=float)])
            raw_delta = np.abs(np.diff(raw_path, axis=0))
            worst_segment = int(raw_delta.max(axis=1).argmax()) if len(raw_delta) else 0
            worst_segment_joint = int(raw_delta[worst_segment].argmax()) if len(raw_delta) else 0
            if worst_segment == 0:
                segment_rows = f"switch_start->{row_start}"
            else:
                segment_rows = f"{row_start + worst_segment - 1}->{row_start + worst_segment}"

            rows.append(
                {
                    "group_idx": group_idx,
                    "row_start": row_start,
                    "row_end": row_start + len(group) - 1,
                    "duration": float(planned[-1, 0]) if len(planned) else 0.0,
                    "peak": float(max_per_joint[peak_joint]),
                    "peak_joint": peak_joint + 1,
                    "peak_time": peak_time,
                    "raw_row": raw_row,
                    "raw_point": raw_idx + 1,
                    "worst_segment": segment_rows,
                    "worst_segment_joint": worst_segment_joint + 1,
                    "worst_segment_delta": float(raw_delta[worst_segment, worst_segment_joint])
                    if len(raw_delta) else 0.0,
                    "max_per_joint": max_per_joint,
                    "planned": planned,
                    "marker": marker,
                }
            )

            if group_idx < len(groups):
                switch_after = SWITCH_AFTER_POINTS_SEQUENCE[
                    (group_idx - 1) % len(SWITCH_AFTER_POINTS_SEQUENCE)
                ]
                switch_time = select_switch_time(marker, switch_after)
                switch_index = int(np.searchsorted(planned[:, 0], switch_time, side="left"))
                switch_index = min(max(0, switch_index), len(planned) - 1)
                q_start = planned[switch_index, 1:7].tolist()
            else:
                q_start = planned[-1, 1:7].tolist()

        rows.sort(key=lambda item: item["peak"], reverse=True)
        print(f"trajectory: {traj_file}")
        print(f"timing_mode={TIMING_MODE}, group_size={GROUP_SIZE}")
        if TIMING_MODE == "timesec":
            print("group_time_secs:", [group_time_sec(i + 1) for i in range(len(groups))])
        else:
            print(f"speed_percent={SPEED_PERCENT}")
        print(f"switch_after_points_sequence={SWITCH_AFTER_POINTS_SEQUENCE}")
        print()
        print("fastest planned segments, estimated from 400Hz q samples:")
        for row in rows:
            max_joints = " ".join(
                f"J{idx + 1}={value:.3f}" for idx, value in enumerate(row["max_per_joint"])
            )
            print(
                f"group {row['group_idx']:02d} rows {row['row_start']:03d}-{row['row_end']:03d}: "
                f"peak J{row['peak_joint']}={row['peak']:.3f} rad/s, "
                f"duration={row['duration']:.3f}s, t={row['peak_time']:.3f}s, "
                f"near raw point {row['raw_point']} row {row['raw_row']}"
            )
            print(
                f"  largest raw jump: {row['worst_segment']} "
                f"on J{row['worst_segment_joint']} delta={row['worst_segment_delta']:.3f} rad"
            )
            print(f"  joint peaks: {max_joints}")
    finally:
        arm.cleanup()


if __name__ == "__main__":
    report()
