import traceback

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
    parse_traj,
    resolve_traj_file,
    select_switch_time,
    original_cmd_points_to_array,
)


ZERO_SEED = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
MAX_SEARCH_TIME_SEC = 60.0


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


def plan_group(arm, q_start, joint_points, gripper, use_time_mode, group_idx, time_override=None):
    if use_time_mode:
        return arm.plan_joint_waypoints_with_gripper(
            q_start,
            joint_points,
            gripper,
            time_sec=group_time_sec(group_idx) if time_override is None else float(time_override),
        )
    return arm.plan_joint_waypoints_with_gripper(
        q_start,
        joint_points,
        gripper,
        speed_percent=SPEED_PERCENT,
    )


def find_min_time_sec(arm, q_start, joint_points, gripper, low_time):
    low = float(low_time)
    high = max(low * 2.0, 0.5)
    last_ok = None
    while high <= MAX_SEARCH_TIME_SEC:
        try:
            last_ok = plan_group(
                arm,
                q_start,
                joint_points,
                gripper,
                True,
                1,
                time_override=high,
            )
            break
        except RuntimeError:
            low = high
            high *= 2.0
    if last_ok is None:
        return None, None

    lo = low
    hi = high
    best = last_ok
    for _ in range(20):
        mid = 0.5 * (lo + hi)
        try:
            best = plan_group(
                arm,
                q_start,
                joint_points,
                gripper,
                True,
                1,
                time_override=mid,
            )
            hi = mid
        except RuntimeError:
            lo = mid
    return hi, best


def precheck():
    use_time_mode = TIMING_MODE == "timesec"
    traj_file = resolve_traj_file()
    entries = parse_traj(traj_file)
    groups = list(frame_groups(entries, GROUP_SIZE))
    if not groups:
        raise RuntimeError(f"no trajectory groups parsed from {traj_file}")

    print(f"precheck trajectory: {traj_file}")
    print(f"groups={len(groups)}, group_size={GROUP_SIZE}, timing_mode={TIMING_MODE}")
    if use_time_mode:
        print("group time schedule:", [group_time_sec(i + 1) for i in range(len(groups))])
    else:
        print(f"speed_percent={SPEED_PERCENT}")
    print(f"switch_after_points_sequence={SWITCH_AFTER_POINTS_SEQUENCE}")

    arm = SingleArm(can_interface_=CAN_INTERFACE, enable_fd_=ENABLE_FD, gripper=True, dry_run=True)
    failures = []
    q_start = None
    try:
        first_group = groups[0][1]
        first_q = solve_joint_waypoints_from_seed(arm, [first_group[0]], ZERO_SEED)[0]
        q_start = first_q
        print("first pose IK ok; using first pose as dry-run start state")

        for group_idx, (row_start, group) in enumerate(groups, 1):
            row_end = row_start + len(group) - 1
            try:
                joint_points = solve_joint_waypoints_from_seed(arm, group, q_start)
                gripper = [frame[6] for frame in group]
                planned = plan_group(arm, q_start, joint_points, gripper, use_time_mode, group_idx)
                planned = np.asarray(planned, dtype=float)
                duration = float(planned[-1, 0]) if planned.size else 0.0
                marker = original_cmd_points_to_array(
                    group,
                    planned,
                    "joint_waypoint_chunk",
                    [0.0, 0.0, 0.0],
                    joint_points=joint_points,
                )
                if group_idx < len(groups):
                    switch_after = SWITCH_AFTER_POINTS_SEQUENCE[
                        (group_idx - 1) % len(SWITCH_AFTER_POINTS_SEQUENCE)
                    ]
                    switch_time = select_switch_time(marker, switch_after)
                    if switch_time is None:
                        switch_index = min(len(planned) - 1, 0)
                    else:
                        switch_index = int(np.searchsorted(planned[:, 0], switch_time, side="left"))
                        switch_index = min(max(0, switch_index), len(planned) - 1)
                    q_start = planned[switch_index, 1:7].tolist()
                    print(
                        f"OK group {group_idx}: rows {row_start}..{row_end}, "
                        f"samples={len(planned)}, duration={duration:.3f}s, "
                        f"next_start_at_point={switch_after}, t={planned[switch_index, 0]:.3f}s"
                    )
                else:
                    q_start = planned[-1, 1:7].tolist()
                    print(
                        f"OK group {group_idx}: rows {row_start}..{row_end}, "
                        f"samples={len(planned)}, duration={duration:.3f}s"
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL group {group_idx}: rows {row_start}..{row_end}: {exc!r}")
                suggested_time = None
                recovered_plan = None
                if use_time_mode and q_start is not None:
                    try:
                        if "joint_points" not in locals() or len(joint_points) != len(group):
                            joint_points = solve_joint_waypoints_from_seed(arm, group, q_start)
                            gripper = [frame[6] for frame in group]
                        suggested_time, recovered_plan = find_min_time_sec(
                            arm,
                            q_start,
                            joint_points,
                            gripper,
                            group_time_sec(group_idx),
                        )
                        if suggested_time is not None:
                            print(
                                f"  suggested minimum time_sec for group {group_idx}: "
                                f"{suggested_time:.3f}s"
                            )
                    except Exception as search_exc:  # noqa: BLE001
                        print(f"  minimum-time search failed: {search_exc!r}")
                failures.append(
                    (group_idx, row_start, row_end, repr(exc), suggested_time, traceback.format_exc())
                )
                if q_start is None:
                    break
                if recovered_plan is not None:
                    planned = np.asarray(recovered_plan, dtype=float)
                    marker = original_cmd_points_to_array(
                        group,
                        planned,
                        "joint_waypoint_chunk",
                        [0.0, 0.0, 0.0],
                        joint_points=joint_points,
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

        if failures:
            print("\nprecheck failures:")
            for group_idx, row_start, row_end, err, suggested_time, _tb in failures:
                suffix = (
                    f"; suggested time_sec >= {suggested_time:.3f}s"
                    if suggested_time is not None else ""
                )
                print(f"- group {group_idx}, rows {row_start}..{row_end}: {err}{suffix}")
            raise RuntimeError(f"precheck failed for {len(failures)} group(s)")
        print("precheck passed")
    finally:
        arm.cleanup()


if __name__ == "__main__":
    precheck()
