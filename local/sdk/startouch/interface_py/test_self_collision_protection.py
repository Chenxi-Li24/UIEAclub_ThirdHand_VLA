import argparse
import time

from startouchclass import SingleArm


HOME = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


CASES = [
    {
        "name": "1测试 J3/J4 组合折回时，夹爪 是否接近 link1。",
        "desc": "测试 J3/J4 组合折回时，夹爪 是否接近 link1。",
        "waypoints": [
            [0.0, 0, -0.7685, 1.0153, 0.0, 0.0],
            [0.0, 0, -0.7685, 1.5153, 0.0, 0.0],
            [0.0, 0, -0.7685, 1.5153, 0.0, 0.0],
        ],
    },
    {
        "name": "2测试 J3/J4 组合折回时，link56 是否接近 link1。",
        "desc": "测试 J3/J4 组合折回时，link56 是否接近 link1。",
        "waypoints": [
            [0.0, 0, -0.37, 0.2934, 0.0, 0.0],
            [0.0, 0, -0.37, 0.634, 0.0, 0.0],
            [0.0, 0, -0.37, 1.1934, 0.0, 0.0],
            # [0.0, 0, -0.37, 1.2934, 0.0, 0.0],
        ],
    },
    {
        "name": "3测试 J3/J4 组合折回时，J6转90°时，夹爪是否接近 link1。",
        "desc": "测试 J3/J4 组合折回时，J6转90°时，夹爪是否接近 link1。",
        "waypoints": [
            [0.0, 0, -0.543, 0.206, 0.0, 1.54],
            [0.0, 0, -0.543, 1.16, 0.0, 1.54],
            [0.0, 0, -0.543, 1.106, 0.0, 1.54],
        ],
    },
    {
        "name": "case4_base_side_sweep",
        "desc": "测试 J5 侧向自碰撞配置是否生效。",
        "waypoints": [
            [0.0, 0, 0, 0, 1.57, 0],
            [0.0, 0, 0, 0, -1.57, 0],
        ],
    },
]


def print_cases():
    print("Self-collision protection cases:")
    for idx, case in enumerate(CASES, 1):
        print(f"{idx}. {case['name']}: {case['desc']}")
        for point in case["waypoints"]:
            print(f"   {point}")


def run_case(arm, case, speed_percent, wait_s):
    print(f"\n[SELF-COLLISION] {case['name']}")
    print(case["desc"])
    try:
        arm.set_joint_waypoints(
            case["waypoints"],
            speed_percent=speed_percent,
        )
    except Exception as exc:
        print(f"保护已触发/轨迹被拒绝: {exc}")
        return
    print("未触发保护，等待轨迹执行完成。若该段本应碰撞，请检查 capsule/box 参数是否过松。")
    time.sleep(wait_s)


def parse_args():
    parser = argparse.ArgumentParser(description="Test self-collision protection with joint waypoints.")
    parser.add_argument("can_interface", nargs="?", default="can0")
    parser.add_argument("--case", type=int, default=0, help="1-based case index; 0 means all cases")
    parser.add_argument("--speed-percent", type=float, default=0.05)
    parser.add_argument("--wait-s", type=float, default=16.0)
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
