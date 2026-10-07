import argparse
import time

from startouchclass import SingleArm


HOME = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


CASES = {
    "planning_time_limit": {
        "desc": "时间模式给很短时间，观察规划摘要和超 velocity/acc/jerk limit 报警；动作幅度小。",
        "waypoints": [[0.0, 0.10, -0.10, 0.08, 0.0, 0.0]],
        "time_sec": 0.12,
        "speed_percent": -1.0,
        "wait_s": 2.0,
    },
    "tracking_error_small": {
        "desc": "低速小幅 waypoint，正常情况下不应触发 tracking_error；用于确认日志和保护无误报。",
        "waypoints": [
            [0.0, 0.08, -0.08, 0.05, 0.0, 0.0],
            [0.0, 0.00, 0.00, 0.00, 0.0, 0.0],
        ],
        "time_sec": 0.0,
        "speed_percent": 0.05,
        "wait_s": 6.0,
    },
    "derivative_watchdog_observe": {
        "desc": "稍快但仍小幅的 waypoint，用于观察 runtime velocity/acc/jerk watchdog 是否报警。",
        "waypoints": [
            [0.0, 0.15, -0.15, 0.10, 0.0, 0.0],
            [0.0, -0.05, 0.05, -0.05, 0.0, 0.0],
            [0.0, 0.00, 0.00, 0.00, 0.0, 0.0],
        ],
        "time_sec": 0.0,
        "speed_percent": 0.20,
        "wait_s": 5.0,
    },
}


def print_cases():
    print("Runtime safety limit cases:")
    for idx, (name, case) in enumerate(CASES.items(), 1):
        print(f"{idx}. {name}: {case['desc']}")
        print(f"   time_sec={case['time_sec']} speed_percent={case['speed_percent']}")
        for q in case["waypoints"]:
            print(f"   {q}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test trajectory limit logs, tracking error, and derivative watchdog safely."
    )
    parser.add_argument("can_interface", nargs="?", default="can0")
    parser.add_argument("--case", choices=list(CASES.keys()), default="tracking_error_small")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--go-home", action="store_true", help="Go HOME before and after selected case")
    return parser.parse_args()


def main():
    args = parse_args()
    print_cases()
    case = CASES[args.case]
    if not args.execute:
        print("\nDry run only. Add --execute to connect. Keep YAML limits conservative.")
        return

    arm = SingleArm(can_interface_=args.can_interface, enable_fd_=False)
    try:
        if args.go_home:
            print("Go HOME")
            arm.set_joint(HOME, tf=3.0)
            time.sleep(3.3)
        print(f"Running case: {args.case}")
        print(case["desc"])
        try:
            motion_kwargs = (
                {"time_sec": case["time_sec"]}
                if case["time_sec"] > 0.0
                else {"speed_percent": case["speed_percent"]}
            )
            arm.set_joint_waypoints(
                case["waypoints"],
                **motion_kwargs,
            )
        except Exception as exc:
            print(f"接口拒绝/保护触发: {exc}")
            return
        print("Command accepted. Watch stderr for planning/runtime protection logs.")
        time.sleep(case["wait_s"])
        if args.go_home:
            print("Return HOME")
            arm.set_joint(HOME, tf=3.0)
            time.sleep(3.3)
    finally:
        arm.cleanup()


if __name__ == "__main__":
    main()
