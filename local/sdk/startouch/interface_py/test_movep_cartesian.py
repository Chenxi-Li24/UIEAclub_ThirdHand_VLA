#!/usr/bin/env python3
import argparse
import time

import numpy as np

from startouchclass import MotionProgram, SingleArm


# ===== User config =====
CAN_INTERFACE = "can0"
USE_MOTION_PROGRAM = True
USE_TIME_MODE = True
TIME_SEC = 2.0
SPEED_PERCENT = 0.2
BLEND_RADIUS_M = 0.002
DX_M = 0.025
DY_M = 0.035
DZ_M = 0.115
POSITION_TOLERANCE_M = 0.002
ORIENTATION_TOLERANCE_RAD = 0.005
SLEEP_BETWEEN_PROGRAM_SEGMENTS_SEC = 2.0


def build_movep_poses_from_current(arm):
    pos, euler = arm.get_ee_pose_euler()
    pos = np.asarray(pos, dtype=float).reshape(3)
    euler = np.asarray(euler, dtype=float).reshape(3)
    return [
        [pos[0], pos[1], pos[2], euler[0], euler[1], euler[2]],
        [pos[0] + DX_M, pos[1], pos[2], euler[0], euler[1], euler[2]],
        [pos[0] + DX_M, pos[1] + DY_M, pos[2] + DZ_M, euler[0], euler[1], euler[2]],
        [pos[0], pos[1] + DY_M, pos[2] + DZ_M, euler[0], euler[1], euler[2]],
    ]


def build_return_poses_from_current_path(poses):
    return [poses[-1], poses[0]]


def build_continuity_test_poses(poses):
    return [
        poses[0],
        poses[1],
        poses[2],
        poses[0],
    ]


def print_poses(name, poses):
    print(f"{name} poses [x, y, z, roll, pitch, yaw]:")
    for i, pose in enumerate(poses, 1):
        print(f"{i}: " + "[" + ", ".join(f"{v:.6f}" for v in pose) + "]")


def main():
    parser = argparse.ArgumentParser(description="Test MoveP Cartesian path execution.")
    parser.add_argument("can_interface", nargs="?", default=CAN_INTERFACE)
    parser.add_argument("--execute", action="store_true", help="Actually connect to robot and execute")
    args = parser.parse_args()

    print("MoveP Cartesian test")
    print("Path: multi-pose Cartesian path with blend radius; quaternion slerp orientation.")
    print(
        f"EXECUTE={args.execute}, USE_MOTION_PROGRAM={USE_MOTION_PROGRAM}, "
        f"USE_TIME_MODE={USE_TIME_MODE}, blend_radius_m={BLEND_RADIUS_M}"
    )
    if not args.execute:
        print("Dry run only. Add --execute to run on hardware.")
        return

    arm = SingleArm(can_interface_=args.can_interface, enable_fd_=False)
    try:
        time.sleep(0.2)
        poses = build_movep_poses_from_current(arm)
        return_poses = build_return_poses_from_current_path(poses)
        continuity_poses = build_continuity_test_poses(poses)
        print_poses("MoveP outbound", poses)
        print_poses("MoveP return", return_poses)
        print_poses("MoveP continuity test", continuity_poses)

        if USE_MOTION_PROGRAM:
            program = MotionProgram()
            if USE_TIME_MODE:
                program.movep(
                    poses,
                    time_sec=TIME_SEC,
                    blend_radius_m=BLEND_RADIUS_M,
                )
                program.sleep(SLEEP_BETWEEN_PROGRAM_SEGMENTS_SEC)
                program.movep(
                    return_poses,
                    time_sec=TIME_SEC ,
                    blend_radius_m=BLEND_RADIUS_M,
                )
                # These consecutive MoveP calls have no sleep between them.
                # They should be merged by MotionProgram and run continuously.
                for pose in continuity_poses:
                    program.movep(
                        pose,
                        time_sec=TIME_SEC,
                        blend_radius_m=BLEND_RADIUS_M,
                    )
            else:
                program.movep(
                    poses,
                    speed_percent=SPEED_PERCENT,
                    blend_radius_m=BLEND_RADIUS_M,
                )
                program.sleep(SLEEP_BETWEEN_PROGRAM_SEGMENTS_SEC)
                program.movep(
                    return_poses,
                    speed_percent=SPEED_PERCENT,
                    blend_radius_m=BLEND_RADIUS_M,
                )
                for pose in continuity_poses:
                    program.movep(
                        pose,
                        speed_percent=SPEED_PERCENT,
                        blend_radius_m=BLEND_RADIUS_M,
                    )
            print("Calling arm.run_motion_program(program); this call should block until all program items finish.")
            start_time = time.monotonic()
            duration = arm.run_motion_program(program)
            wall_time = time.monotonic() - start_time
            print(
                f"run_motion_program returned: motion_duration_s={duration:.3f}, "
                f"wall_time_s={wall_time:.3f}"
            )
        else:
            if USE_TIME_MODE:
                print("Calling arm.move_p(...); this call should block until MoveP finishes.")
                start_time = time.monotonic()
                duration = arm.move_p(
                    poses,
                    time_sec=TIME_SEC,
                    blend_radius_m=BLEND_RADIUS_M,
                    position_tolerance_m=POSITION_TOLERANCE_M,
                    orientation_tolerance_rad=ORIENTATION_TOLERANCE_RAD,
                )
                wall_time = time.monotonic() - start_time
            else:
                print("Calling arm.move_p(...); this call should block until MoveP finishes.")
                start_time = time.monotonic()
                duration = arm.move_p(
                    poses,
                    speed_percent=SPEED_PERCENT,
                    blend_radius_m=BLEND_RADIUS_M,
                    position_tolerance_m=POSITION_TOLERANCE_M,
                    orientation_tolerance_rad=ORIENTATION_TOLERANCE_RAD,
                )
                wall_time = time.monotonic() - start_time
            print(f"move_p returned: motion_duration_s={duration:.3f}, wall_time_s={wall_time:.3f}")
        print(f"MoveP completed. planned_motion_duration_s={duration:.3f}")
    finally:
        arm.cleanup()


if __name__ == "__main__":
    main()
