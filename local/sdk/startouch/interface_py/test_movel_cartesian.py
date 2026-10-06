#!/usr/bin/env python3
import time

import numpy as np

from startouchclass import SingleArm


# ===== User config =====
EXECUTE = True
CAN_INTERFACE = "can0"
USE_TIME_MODE = True
TIME_SEC = 3.0
SPEED_PERCENT = 0.2
DX_M = 0.050
DZ_M = 0.155
POSITION_TOLERANCE_M = 0.003
ORIENTATION_TOLERANCE_RAD = 0.05


def build_movel_poses_from_current(arm):
    pos, euler = arm.get_ee_pose_euler()
    pos = np.asarray(pos, dtype=float).reshape(3)
    euler = np.asarray(euler, dtype=float).reshape(3)
    return [
        [pos[0], pos[1], pos[2], euler[0], euler[1], euler[2]],
        [pos[0] + DX_M, pos[1], pos[2], euler[0], euler[1], euler[2]],
        [pos[0] + DX_M, pos[1], pos[2] + DZ_M, euler[0], euler[1], euler[2]],
        [pos[0], pos[1], pos[2] + DZ_M, euler[0], euler[1], euler[2]],
        [pos[0], pos[1], pos[2], euler[0], euler[1], euler[2]],
    ]


def print_poses(poses):
    print("MoveL poses [x, y, z, roll, pitch, yaw]:")
    for i, pose in enumerate(poses, 1):
        print(f"{i}: " + "[" + ", ".join(f"{v:.6f}" for v in pose) + "]")


def main():
    print("MoveL Cartesian test")
    print("Path: current TCP -> rectangle in X/Z -> current TCP")
    print(f"EXECUTE={EXECUTE}, USE_TIME_MODE={USE_TIME_MODE}")
    if not EXECUTE:
        print("Dry run only. Set EXECUTE = True in this file to run on hardware.")
        return

    arm = SingleArm(can_interface_=CAN_INTERFACE, enable_fd_=False)
    try:
        time.sleep(0.2)
        poses = build_movel_poses_from_current(arm)
        print_poses(poses)
        if USE_TIME_MODE:
            duration = arm.move_l(
                poses,
                time_sec=TIME_SEC,
                blend_radius_m=0.0,
                position_tolerance_m=POSITION_TOLERANCE_M,
                orientation_tolerance_rad=ORIENTATION_TOLERANCE_RAD,
            )
        else:
            duration = arm.move_l(
                poses,
                speed_percent=SPEED_PERCENT,
                blend_radius_m=0.0,
                position_tolerance_m=POSITION_TOLERANCE_M,
                orientation_tolerance_rad=ORIENTATION_TOLERANCE_RAD,
            )
        print(f"MoveL completed. planned_duration_s={duration:.3f}")
    finally:
        arm.cleanup()


if __name__ == "__main__":
    main()
