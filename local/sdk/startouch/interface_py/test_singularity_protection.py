import argparse
import time

from startouchclass import SingleArm


HOME = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


CASES = [
    {
        "name": "case1_wrist_positive_90deg",
        "desc": "测试腕部奇异：Joint5 接近 +90deg，Joint4/Joint6 轴线趋于重合。",
        "waypoints": [
            [0.0, 0.80, -1.20, 0.35, 1.30, 0.0],
            [0.0, 0.90, -1.35, 0.45, 1.50, 0.0],
            [0.0, 0.95, -1.45, 0.50, 1.5708, 0.0],
        ],
    },
    {
        "name": "case2_wrist_negative_90deg",
        "desc": "测试腕部奇异：Joint5 接近 -90deg，Joint4/Joint6 轴线趋于重合。",
        "waypoints": [
            [0.0, 0.80, -1.20, 0.35, -1.30, 0.0],
            [0.0, 0.90, -1.35, 0.45, -1.50, 0.0],
            [0.0, 0.95, -1.45, 0.50, -1.5708, 0.0],
        ],
    },
    {
        "name": "case3_elbow_singularity",
        "desc": "测试肘部奇异：Joint3=-166.83deg 且 Joint4=-15.33deg 附近。",
        "waypoints": [
            [0.0, 1.10, -2.30, -0.10, 0.0, 0.0],
            [0.0, 1.30, -2.70, -0.20, 0.0, 0.0],
            [0.0, 1.45, -2.912226, -0.267559, 0.0, 0.0],
        ],
    },
    {
        "name": "case4_shoulder_singularity_candidate",
        "desc": "测试肩部奇异候选：调整 J2/J3/J4 使 Joint5_Origin 靠近 Joint1 Z 轴。",
        "waypoints": [
            [0.0, 0.65, -1.20, 0.55, 0.0, 0.0],
            [0.0, 0.25, -0.55, 0.30, 0.0, 0.0],
            [0.0, -0.10, -0.10, -0.20, 0.0, 0.0],
        ],
    },
    {
        "name": "case5_jacobian_combined_singularity",
        "desc": "测试 Jacobian 兜底：腕部接近奇异，同时肘部接近折叠，检查组合奇异是否被拒绝。",
        "waypoints": [
            [0.0, 1.00, -2.20, -0.10, 1.20, 0.0],
            [0.0, 1.25, -2.65, -0.22, 1.45, 0.8],
            [0.0, 1.45, -2.90, -0.267559, 1.5708, 1.5],
        ],
    },
]


def print_cases():
    print("Singularity protection cases:")
    for idx, case in enumerate(CASES, 1):
        print(f"{idx}. {case['name']}: {case['desc']}")
        for point in case["waypoints"]:
            print(f"   {point}")


def run_case(arm, case, speed_percent, wait_s):
    print(f"\n[SINGULARITY] {case['name']}")
    print(case["desc"])
    print("Expected logs:")
    print("  - [set_joint_waypoints] safety warning ... speed_scale=... means yellow-zone slowdown")
    print("  - [set_joint_waypoints] inserted singularity avoidance waypoint ... means auto bypass")
    print("  - singularity_stop means the trajectory was rejected after bypass attempts")
    try:
        arm.set_joint_waypoints(
            case["waypoints"],
            speed_percent=speed_percent,
        )
    except Exception as exc:
        print(f"保护已触发/轨迹被拒绝: {exc}")
        return
    print("命令已接受。请观察上方日志中的 samples、duration、实际最大速度/加速度/jerk、降速或绕行信息。")
    time.sleep(wait_s)


def parse_args():
    parser = argparse.ArgumentParser(description="Test singularity protection with joint waypoints.")
    parser.add_argument("can_interface", nargs="?", default="can0")
    parser.add_argument("--case", type=int, default=0, help="1-based case index; 0 means all cases")
    parser.add_argument("--speed-percent", type=float, default=0.05)
    parser.add_argument("--wait-s", type=float, default=8.0)
    parser.add_argument("--execute", action="store_true", help="Actually connect to robot and execute tests")
    return parser.parse_args()


def main():
    args = parse_args()
    print_cases()
    if not args.execute:
        print("\nDry run only. Add --execute to connect to the robot.")
        return

    selected = CASES if args.case == 0 else [CASES[args.case - 1]]
    arm = SingleArm(can_interface_=args.can_interface, enable_fd_=False)
    try:
        print("\nGo HOME")
        arm.set_joint(HOME, tf=3.0)
        time.sleep(3.2)
        for case in selected:
            run_case(arm, case, args.speed_percent, args.wait_s)
            print("Return HOME")
            arm.set_joint(HOME, tf=3.0)
            time.sleep(3.2)
    finally:
        arm.cleanup()


if __name__ == "__main__":
    main()
