#!/usr/bin/env python3
import threading
import time

from startouchclass import MotionProgram, SingleArm


# ===== User config =====
EXECUTE = True
LEFT_CAN_INTERFACE = "can0"
RIGHT_CAN_INTERFACE = "can1"
SPEED_PERCENT = 0.3
TIME_SEC = 1.0
PROGRAM_SLEEP_SEC = 1.0
HOME_SLEEP_SEC = 3.2

LEFT_HOME = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
RIGHT_HOME = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

# MOVEJW1 and MOVEJW2 are continuous because there is no sleep between them.
LEFT_MOVEJW1 = [
    [0.0, 0.00, -0.25, 0.35, 0.0, 0.0],
    [0.0, 0.12, -0.42, 0.52, 0.0, 0.0],
]
LEFT_MOVEJW2 = [
    [0.0, 0.20, -0.50, 0.70, 0.0, 0.0],
    [0.0, 0.08, -0.35, 0.45, 0.0, 0.0],
]
LEFT_MOVEJW3 = [
    [0.0, 0.00, -0.25, 0.35, 0.0, 0.0],
    LEFT_HOME,
]

RIGHT_MOVEJW1 = [
    [0.0, 0.00, -0.25, 0.35, 0.0, 0.0],
    [0.0, 0.12, -0.42, 0.52, 0.0, 0.0],
]
RIGHT_MOVEJW2 = [
    [0.0, 0.20, -0.50, 0.70, 0.0, 0.0],
    [0.0, 0.08, -0.35, 0.45, 0.0, 0.0],
]
RIGHT_MOVEJW3 = [
    [0.0, 0.00, -0.25, 0.35, 0.0, 0.0],
    RIGHT_HOME,
]


def build_program(movejw1, movejw2, movejw3):
    program = MotionProgram()
    # program.movej(movejw1, speed_percent=SPEED_PERCENT)
    # program.movej(movejw2, speed_percent=SPEED_PERCENT)
    # program.sleep(PROGRAM_SLEEP_SEC)
    # program.movej(movejw3, speed_percent=SPEED_PERCENT)
    program.movej(movejw1, time_sec=TIME_SEC)
    program.movej(movejw2, time_sec=TIME_SEC)
    program.sleep(PROGRAM_SLEEP_SEC)
    program.movej(movejw3, time_sec=TIME_SEC)
    return program


def run_arm_program(name, arm, program, results):
    start = time.monotonic()
    try:
        motion_time = arm.run_motion_program(program)
        results[name] = {
            "ok": True,
            "motion_time": motion_time,
            "wall_time": time.monotonic() - start,
            "error": "",
        }
    except Exception as exc:
        results[name] = {
            "ok": False,
            "motion_time": 0.0,
            "wall_time": time.monotonic() - start,
            "error": str(exc),
        }


def print_program(name, movejw1, movejw2, movejw3):
    print(f"{name}:")
    print(f"  MOVEJW1: {movejw1}")
    print(f"  MOVEJW2: {movejw2}")
    print(f"  SLEEP:   {PROGRAM_SLEEP_SEC} s")
    print(f"  MOVEJW3: {movejw3}")


def main():
    print("Dual-arm MotionProgram MoveJ test")
    print("Semantics: MOVEJW1 and MOVEJW2 are continuous; sleep stops before MOVEJW3.")
    print(f"EXECUTE={EXECUTE}, speed_percent={SPEED_PERCENT}")
    print_program("left", LEFT_MOVEJW1, LEFT_MOVEJW2, LEFT_MOVEJW3)
    print_program("right", RIGHT_MOVEJW1, RIGHT_MOVEJW2, RIGHT_MOVEJW3)

    if not EXECUTE:
        print("Dry run only. Set EXECUTE = True in this file to run on hardware.")
        return

    left_arm = SingleArm(can_interface_=LEFT_CAN_INTERFACE, enable_fd_=False)
    right_arm = SingleArm(can_interface_=RIGHT_CAN_INTERFACE, enable_fd_=False)
    try:
        print("Going HOME on both arms...")
        left_arm.set_joint(LEFT_HOME, tf=3.0)
        right_arm.set_joint(RIGHT_HOME, tf=3.0)
        time.sleep(HOME_SLEEP_SEC)

        left_program = build_program(LEFT_MOVEJW1, LEFT_MOVEJW2, LEFT_MOVEJW3)
        right_program = build_program(RIGHT_MOVEJW1, RIGHT_MOVEJW2, RIGHT_MOVEJW3)

        results = {}
        left_thread = threading.Thread(
            target=run_arm_program,
            args=("left", left_arm, left_program, results),
            daemon=False,
        )
        right_thread = threading.Thread(
            target=run_arm_program,
            args=("right", right_arm, right_program, results),
            daemon=False,
        )

        start = time.monotonic()
        left_thread.start()
        right_thread.start()
        left_thread.join()
        right_thread.join()
        print(f"Total wall time: {time.monotonic() - start:.3f} s")

        for name in ("left", "right"):
            result = results.get(name, {"ok": False, "error": "thread did not report result"})
            print(f"{name}: {result}")
            if not result["ok"]:
                raise RuntimeError(f"{name} arm failed: {result['error']}")
    finally:
        left_arm.cleanup()
        right_arm.cleanup()


if __name__ == "__main__":
    main()
