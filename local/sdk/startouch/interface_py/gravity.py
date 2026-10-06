from startouchclass import SingleArm
import time

# 创建机械臂连接  连接接口为"can0"
arm_controller = SingleArm(can_interface_ = "can0")
time.sleep(3)

try:
    print("重力补偿已启动，按ESC键退出...")
    while True:
        # 执行重力补偿
        arm_controller.gravity_compensation()
        print(arm_controller.get_ee_pose_quat())
        # 短暂延时，避免过度占用CPU
        time.sleep(0.01)
        
except KeyboardInterrupt:
    print("\n程序被用户中断")
except Exception as e:
    print(f"发生错误: {e}")
finally:
    print("重力补偿循环结束")

arm_controller.cleanup()

