import math
import sys
import termios
import time
import tty

import numpy as np

from startouchclass import SingleArm


# ================== 初始化机械臂 ==================
arm_controllers = [
    SingleArm(can_interface_="can0", enable_fd_=False),
    # SingleArm(can_interface_="can1", enable_fd_=False),
]
time.sleep(3)

# ================== 参数 ==================
POS_STEP = 0.005
RPY_STEP = math.radians(2.0)
GRIPPER_STEP = 0.05

gripper_pos = None


# ================== 终端按键工具 ==================
def getch():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def print_help():
    print("""
========== Cartesian Keyboard Control ==========
Position:
  w/s : +X / -X
  a/d : +Y / -Y
  r/f : +Z / -Z

Orientation (RPY):
  i/k : +Roll / -Roll
  j/l : +Pitch / -Pitch
  u/o : +Yaw / -Yaw

Gripper:
  z/x : open / close

Other:
  space : print current pose
  q     : go home and quit
===============================================
""")


def send_pose_to_all(pos_, euler_):
    for arm in arm_controllers:
        arm.set_end_effector_pose_euler_raw(pos_, euler_)


def send_gripper_to_all(gripper_pos_):
    for arm in arm_controllers:
        arm.setGripperPosition(gripper_pos_)


def go_home_all():
    for arm in arm_controllers:
        arm.go_home()


def get_initial_pose():
    default_pos = np.array([0.2833, 0.0, 0.17605], dtype=float)
    default_euler = np.array([0.0, 0.0, 0.0], dtype=float)
    try:
        pos_, euler_ = arm_controllers[0].get_ee_pose_euler()
        return np.array(pos_, dtype=float), np.array(euler_, dtype=float)
    except Exception as e:
        print(f"读取当前末端位姿失败，使用默认初始位姿: {e}")
        return default_pos, default_euler


def get_initial_gripper():
    try:
        return float(arm_controllers[0].get_gripper_position())
    except Exception as e:
        print(f"读取当前夹爪位置失败，启动时不发送夹爪命令: {e}")
        return None


def cleanup_all():
    for arm in arm_controllers:
        arm.cleanup()


def main():
    global gripper_pos

    print_help()
    pos, euler = get_initial_pose()
    gripper_pos = get_initial_gripper()
    print(f"initial pos = {pos}, initial euler(rpy) = {euler}")
    if gripper_pos is not None:
        print(f"initial gripper = {gripper_pos:.3f}")

    while True:
        key = getch()

        pose_updated = False
        gripper_updated = False

        # -------- Position --------
        if key == "w":
            pos[0] += POS_STEP
            pose_updated = True
        elif key == "s":
            pos[0] -= POS_STEP
            pose_updated = True
        elif key == "a":
            pos[1] += POS_STEP
            pose_updated = True
        elif key == "d":
            pos[1] -= POS_STEP
            pose_updated = True
        elif key == "r":
            pos[2] += POS_STEP
            pose_updated = True
        elif key == "f":
            pos[2] -= POS_STEP
            pose_updated = True

        # -------- Orientation --------
        elif key == "i":
            euler[0] += RPY_STEP
            pose_updated = True
        elif key == "k":
            euler[0] -= RPY_STEP
            pose_updated = True
        elif key == "j":
            euler[1] += RPY_STEP
            pose_updated = True
        elif key == "l":
            euler[1] -= RPY_STEP
            pose_updated = True
        elif key == "u":
            euler[2] += RPY_STEP
            pose_updated = True
        elif key == "o":
            euler[2] -= RPY_STEP
            pose_updated = True

        # -------- Gripper --------
        elif key == "z":
            if gripper_pos is None:
                gripper_pos = 0.0
            gripper_pos = min(1.0, gripper_pos + GRIPPER_STEP)
            gripper_updated = True
        elif key == "x":
            if gripper_pos is None:
                gripper_pos = 0.0
            gripper_pos = max(0.0, gripper_pos - GRIPPER_STEP)
            gripper_updated = True

        # -------- Other --------
        elif key == " ":
            try:
                cur_pos, cur_euler = arm_controllers[0].get_ee_pose_euler()
                cur_gripper = arm_controllers[0].get_gripper_position()
                q = arm_controllers[0].get_joint_positions()
                print("Q:", q)
                print(
                    f"target pos = {pos}, target euler(rpy) = {euler}, target gripper = {gripper_pos}"
                )
                print(
                    f"current pos = {np.array(cur_pos)}, current euler(rpy) = {np.array(cur_euler)}, current gripper = {float(cur_gripper):.3f}"
                )
            except Exception as e:
                print(f"读取当前末端状态失败: {e}")
        elif key == "q":
            print("Exit.")
            go_home_all()
            time.sleep(4)
            break

        # -------- Send command --------
        if pose_updated or gripper_updated:
            st = time.time()
            if pose_updated:
                send_pose_to_all(pos, euler)
            if gripper_updated:
                send_gripper_to_all(gripper_pos)
            print("", time.time() - st)


try:
    main()
finally:
    cleanup_all()
