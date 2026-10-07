import numpy as np
import sys, termios, tty, time, math
from typing import Tuple
# 创建 ArmController 对象，使用默认构造函数
import os
from startouchclass import SingleArm

print("Creating controller instance")
arm_controller_0 = SingleArm(can_interface_ = "can0",enable_fd_ = False)
#arm_controller_1 = SingleArm(can_interface_ = "can1",enable_fd_ = False)
time.sleep(3)
# print("Solving IK")
# q_sol, ok = arm_controller_0.solve_ik([0.2025, 0.0, 0.45], [1.0, 0.0, 0.0, 0.0])
# q_sol, ok = arm_controller_1.solve_ik([0.2025, 0.0, 0.45], [1.0, 0.0, 0.0, 0.0])
# arm_controller_0.setGripperPosition(1)
# arm_controller_1.setGripperPosition(1.5)
# print(q_sol)
# time.sleep(20)



# arm_controller_0.set_joint([0, 0.5, 0, 0.5, 0, 0], 2.0)
# time.sleep(2)
# arm_controller_0.set_end_effector_pose_euler([0.3, 0.0, 0.16], [0.0, 0.0, 0.0], 2.0)

# time.sleep(1000)
##查看是否正常初始化，电机使能


