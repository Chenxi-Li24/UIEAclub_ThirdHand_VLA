#!/usr/bin/env python3
import argparse
import time

from startouchclass import MotionProgram, SingleArm


HOME = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def main():
    parser = argparse.ArgumentParser(
        description="Test blocking move_joint_waypoints and MotionProgram MoveJ/Sleep semantics."
    )
    parser.add_argument("--can-interface", default="can0")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--speed-percent", type=float, default=0.3)
    args = parser.parse_args()

    move_a = [
        [0.0, 0.0, -0.25, 0.35, 0.0, 0.0],
        [0.0, 0.15, -0.45, 0.55, 0.0, 0.0],
    ]
    move_b = [
        [0.0, 0.25, -0.55, 0.75, 0.0, 0.0],
        [0.0, 0.10, -0.35, 0.45, 0.0, 0.0],
    ]
    move_c = [
        [0.0, 0.0, -0.25, 0.35, 0.0, 0.0],
        HOME,
    ]

    print("Single blocking MoveJ:")
    print("  arm.set_joint_waypoints(move_a, speed_percent=...)")
    print("  returns after move_a is finished; returned value is planned duration_s.")
    print()
    print("MotionProgram:")
    print("  movej(move_a)")
    print("  movej(move_b)   # continuous with previous movej")
    print("  sleep(1.0)      # blocking breakpoint; robot stops before sleep")
    print("  movej(move_c)   # starts after sleep")

    if not args.execute:
        print()
        print("Dry run only. Add --execute to run on hardware.")
        return

    arm = SingleArm(can_interface_=args.can_interface, enable_fd_=False)
    try:
        print("Going HOME with set_joint(tf=3.0)...")
        arm.set_joint(HOME, tf=3.0)
        time.sleep(3.2)

        start = time.monotonic()
        duration = arm.set_joint_waypoints(move_a, speed_percent=args.speed_percent)
        elapsed = time.monotonic() - start
        print(f"Blocking MoveJ returned duration_s={duration:.3f}, wall_elapsed_s={elapsed:.3f}")

        program = MotionProgram()
        program.movej(move_a, speed_percent=args.speed_percent)
        program.movej(move_b, speed_percent=args.speed_percent)
        program.sleep(1.0)
        program.movej(move_c, speed_percent=args.speed_percent)

        start = time.monotonic()
        total_motion = arm.run_motion_program(program)
        elapsed = time.monotonic() - start
        print(
            f"MotionProgram returned motion_duration_s={total_motion:.3f}, "
            f"wall_elapsed_s={elapsed:.3f}"
        )
    finally:
        arm.cleanup()


if __name__ == "__main__":
    main()
