import argparse
import time

from startouchclass import SingleArm


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test mounting gravity direction and MIT feedforward compensation."
    )
    parser.add_argument("can_interface", nargs="?", default="can0")
    parser.add_argument("--mode", choices=["hold", "gravity"], default="gravity")
    parser.add_argument("--duration-s", type=float, default=20.0)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually connect and enable motors. Without this flag only prints instructions.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print("Mounting/gravity compensation test")
    print("Before running, set src/config/robot_kinematics.yaml:")
    print("  kinematics.mounting.mode: upright | inverted | left_wall | right_wall")
    print("  mit_mode.enable_gravity_compensation/coriolis/inertia")
    print("  mit_mode.feedforward_tau_limits")
    print("")
    if not args.execute:
        print("Dry run only. Add --execute after supporting the arm safely.")
        return

    arm = SingleArm(can_interface_=args.can_interface, enable_fd_=False)
    try:
        print("Current joints:", arm.get_joint_positions())
        if args.mode == "gravity":
            print("Entering KDL gravity/feedforward compensation mode.")
            print("Keep a hand near the E-stop. The arm should feel light if mounting mode is correct.")
            arm.gravity_compensation()
        else:
            print("Holding current mode without entering gravity compensation.")
        t0 = time.time()
        while time.time() - t0 < args.duration_s:
            q = arm.get_joint_positions()
            tau = arm.get_joint_torques()
            print(
                f"t={time.time() - t0:6.2f}s q="
                + "[" + ", ".join(f"{v:+.3f}" for v in q) + "] "
                + "tau=[" + ", ".join(f"{v:+.2f}" for v in tau) + "]"
            )
            time.sleep(0.5)
    finally:
        arm.cleanup()


if __name__ == "__main__":
    main()
