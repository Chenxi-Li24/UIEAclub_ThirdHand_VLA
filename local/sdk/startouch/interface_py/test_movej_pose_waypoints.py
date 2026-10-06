import argparse
import time

import numpy as np

from startouchclass import SingleArm


def make_poses_from_current(arm, dx, dz):
    pos, euler = arm.get_ee_pose_euler()
    pos = np.asarray(pos, dtype=float)
    euler = np.asarray(euler, dtype=float)
    poses = [
        [pos[0], pos[1], pos[2], euler[0], euler[1], euler[2]],
        [pos[0] + dx, pos[1], pos[2] + dz, euler[0], euler[1], euler[2]],
        [pos[0], pos[1], pos[2], euler[0], euler[1], euler[2]],
    ]
    return poses


def print_poses(poses):
    print("MOVEJ_POSE waypoints [x, y, z, roll, pitch, yaw]:")
    for idx, pose in enumerate(poses, 1):
        print(f"{idx}. " + "[" + ", ".join(f"{v:.6f}" for v in pose) + "]")


def parse_args():
    parser = argparse.ArgumentParser(description="Test public MoveP Cartesian pose execution.")
    parser.add_argument("can_interface", nargs="?", default="can0")
    parser.add_argument("--dx", type=float, default=0.015, help="Small TCP x offset in meters")
    parser.add_argument("--dz", type=float, default=0.010, help="Small TCP z offset in meters")
    parser.add_argument("--time-sec", type=float, default=6.0, help="Strict total trajectory time")
    parser.add_argument(
        "--speed-percent",
        type=float,
        default=-1.0,
        help="If >0, use speed-percent mode and time-sec becomes inactive",
    )
    parser.add_argument("--position-tolerance-m", type=float, default=0.005)
    parser.add_argument("--orientation-tolerance-rad", type=float, default=0.05)
    parser.add_argument("--execute", action="store_true", help="Actually connect to robot and execute")
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.execute:
        print("Dry run only. Add --execute to connect and build poses from current TCP pose.")
        print(f"Planned relative test offsets: dx={args.dx:.4f}m, dz={args.dz:.4f}m")
        return

    arm = SingleArm(can_interface_=args.can_interface, enable_fd_=False)
    try:
        time.sleep(0.2)
        poses = make_poses_from_current(arm, args.dx, args.dz)
        print_poses(poses)
        motion_kwargs = (
            {"speed_percent": args.speed_percent}
            if args.speed_percent > 0.0
            else {"time_sec": args.time_sec}
        )
        arm.move_p(
            poses,
            **motion_kwargs,
            blend_radius_m=0.0,
            position_tolerance_m=args.position_tolerance_m,
            orientation_tolerance_rad=args.orientation_tolerance_rad,
        )
        wait_s = args.time_sec + 1.0 if args.speed_percent <= 0.0 else 8.0
        print(f"Command sent. Waiting {wait_s:.1f}s for execution.")
        time.sleep(wait_s)
    finally:
        arm.cleanup()


if __name__ == "__main__":
    main()
