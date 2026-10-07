import numpy as np
import sys, termios, tty, time, math
from startouchclass import SingleArm

# ================== 初始化机械臂 ==================
arm_controller = SingleArm(can_interface_="can0", enable_fd_=False)

# ================== 参数 ==================
POS_STEP = 0.01          # 2 mm

pos = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

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
  w/s : +mot1 / -mot1
  e/d : +mot2 / -mot2
  r/f : +mot3 / -mot3
  t/g : +mot4 / -mot4
  y/h : +mot5 / -mot5
  u/j : +mot6 / -mot6
          
Other:
  space : print current pose
  q     : quit
===============================================
""")

# ================== 主循环 ==================
print_help()
arm_controller.go_home()

while True:
    key = getch()

    updated = False

    # -------- Position --------
    if key == 'w':
        pos[0] += POS_STEP
        updated = True
    elif key == 's':
        pos[0] -= POS_STEP
        updated = True
    elif key == 'e':
        pos[1] += POS_STEP
        updated = True
    elif key == 'd':
        pos[1] -= POS_STEP
        updated = True
    elif key == 'r':
        pos[2] += POS_STEP
        updated = True
    elif key == 'f':
        pos[2] -= POS_STEP
        updated = True
    elif key == 't':
        pos[3] += POS_STEP
        updated = True
    elif key == 'g':
        pos[3] -= POS_STEP
        updated = True
    elif key == 'y':
        pos[4] += POS_STEP
        updated = True
    elif key == 'h':
        pos[4] -= POS_STEP
        updated = True
    elif key == 'u':
        pos[5] += POS_STEP
        updated = True
    elif key == 'j':
        pos[5] -= POS_STEP
        updated = True

    # -------- Other --------
    elif key == ' ':
        gpos = arm_controller.get_joint_positions()
        print(gpos)
    elif key == 'q':
        print("Exit.")
        arm_controller.go_home()
        break

    # -------- Send command --------
    if updated:
        st=time.time()
        arm_controller.set_joint(pos,tf=0.0001)
        print("",time.time()-st)

