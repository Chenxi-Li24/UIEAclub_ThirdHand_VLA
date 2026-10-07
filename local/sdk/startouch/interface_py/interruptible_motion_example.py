#!/usr/bin/env python3
import argparse
import signal
import threading
import time
from dataclasses import dataclass
from typing import Optional

from startouchclass import MotionProgram, SingleArm


HOME = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


@dataclass
class MotionResult:
    duration: float = 0.0
    error: Optional[BaseException] = None


def run_blocking_call(call_fn, *args, **kwargs) -> tuple[threading.Thread, MotionResult]:
    result = MotionResult()

    def worker():
        try:
            result.duration = call_fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            result.error = exc

    thread = threading.Thread(target=worker, daemon=False)
    thread.start()
    return thread, result


def main():
    parser = argparse.ArgumentParser(
        description="Example of running blocking waypoint or MotionProgram calls with Ctrl+C handling."
    )
    parser.add_argument("can_interface", nargs="?", default="can0")
    parser.add_argument("--mode", choices=["waypoints", "program"], default="waypoints")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    waypoints = [
        HOME,
        [0.0, 0.12, -0.30, 0.35, 0.0, 0.0],
        [0.0, 0.18, -0.42, 0.50, 0.0, 0.0],
        HOME,
    ]

    if not args.execute:
        print("Dry run only. Add --execute to connect to hardware.")
        print("Ctrl+C handling pattern: run blocking motion in a worker thread, then cleanup on interrupt.")
        return

    stop_requested = threading.Event()

    def handle_sigint(signum, frame):  # noqa: ARG001
        stop_requested.set()

    signal.signal(signal.SIGINT, handle_sigint)

    arm = SingleArm(can_interface_=args.can_interface, gripper=True, enable_fd_=False)
    try:
        time.sleep(0.2)
        if args.mode == "program":
            program = MotionProgram()
            program.movej(waypoints[:2], time_sec=2.0)
            program.sleep(0.5)
            program.movej(waypoints[2:], time_sec=2.0)
            thread, result = run_blocking_call(arm.run_motion_program, program)
        else:
            thread, result = run_blocking_call(arm.set_joint_waypoints, waypoints, time_sec=4.0)

        while thread.is_alive():
            thread.join(timeout=0.05)
            if stop_requested.is_set():
                print("Interrupt requested. Calling cleanup(); use hardware E-stop for immediate stop.")
                arm.cleanup()
                break

        thread.join(timeout=2.0)
        if result.error is not None:
            raise result.error
        print(f"motion_duration_s={result.duration:.3f}")
    finally:
        arm.cleanup()


if __name__ == "__main__":
    main()
