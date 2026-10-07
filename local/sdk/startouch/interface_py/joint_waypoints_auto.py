import argparse
import signal
import threading
import time
from dataclasses import dataclass
from typing import Optional

from startouchclass import SingleArm


HOME = [0, 0, 0, 0, 0, 0]

PATH = [
    [0, 1.54, -3, 1.29, 0, 0],
    [2.7, 1.54, -3, 1.29, 1.6, -2.7],
    [-2.7, 1.54, -3, 0, -1.6, 2.7],
    [0, 0, 0, 0, 0, 0],
    [0, 3.2, -1.5, 0, 0, 0],
    [0, -0.13, 0, -1.29, 0, 0],
]


@dataclass
class MotionResult:
    duration: float = 0.0
    error: Optional[BaseException] = None


def run_motion_thread(call_fn, *args, **kwargs) -> tuple[threading.Thread, MotionResult]:
    result = MotionResult()

    def worker():
        try:
            result.duration = call_fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            result.error = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread, result


def interruptible_sleep(seconds: float, stop_requested: threading.Event):
    deadline = time.monotonic() + max(0.0, seconds)
    while not stop_requested.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return
        time.sleep(min(0.05, remaining))
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("can_interface", nargs="?", default="can0")
    parser.add_argument("--speed-percent", type=float, default=0.1)
    parser.add_argument("--time-sec", type=float, default=0.0)
    parser.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args()

    stop_requested = threading.Event()
    cleanup_started = threading.Event()

    def request_stop(signum, frame):  # noqa: ARG001
        stop_requested.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    arm = SingleArm(can_interface_=args.can_interface, enable_fd_=False)

    def cleanup_once():
        if cleanup_started.is_set():
            return
        cleanup_started.set()
        arm.cleanup()

    def return_home_after_interrupt():
        print("Returning to zero position after interrupt.")
        cleanup_once()
        home_arm = SingleArm(can_interface_=args.can_interface, enable_fd_=False)
        try:
            home_arm.set_joint_waypoints([HOME], time_sec=3.0)
        finally:
            home_arm.cleanup()

    try:
        print("go home")
        arm.set_joint(HOME, tf=3)
        interruptible_sleep(3.2, stop_requested)

        for i in range(max(1, args.cycles)):
            if stop_requested.is_set():
                raise KeyboardInterrupt
            print(f"cycle {i + 1}")
            motion_kwargs = (
                {"time_sec": args.time_sec}
                if args.time_sec > 0.0
                else {"speed_percent": args.speed_percent}
            )
            thread, result = run_motion_thread(
                arm.set_joint_waypoints,
                PATH,
                **motion_kwargs,
            )
            while thread.is_alive():
                thread.join(timeout=0.05)
                if stop_requested.is_set():
                    print("Interrupt requested. Cleaning up controller resources.")
                    cleanup_once()
                    thread.join(timeout=2.0)
                    raise KeyboardInterrupt
            if result.error is not None:
                raise result.error

            wait_s = args.time_sec + 1.0 if args.time_sec > 0 else 30.0
            interruptible_sleep(wait_s, stop_requested)

        print("return home")
        arm.set_joint(HOME, tf=3)
        interruptible_sleep(3.2, stop_requested)
    except KeyboardInterrupt:
        print("Interrupted by user. Controller cleanup requested.")
        return_home_after_interrupt()
    finally:
        cleanup_once()


if __name__ == "__main__":
    main()
