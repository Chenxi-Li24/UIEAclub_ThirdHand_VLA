import time
import rclpy
import threading
import numpy as np
from rclpy.node import Node
from sensor_msgs.msg import JointState

from startouchclass import SingleArm

class MainArmJointPublisher(Node):
    def __init__(self):
        super().__init__('main_arm_joint_publisher_right')

        # 1. 定义关节名称
        self.joint_names = ["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "gripper"]

        # 2. 初始化主臂控制器
        self.arm_controller = SingleArm(can_interface_="can0", enable_fd_=False) # 主臂
        self.arm_follower = SingleArm(can_interface_="can1", enable_fd_=False) # 从臂
        
        time.sleep(2)
        self.vel_filtered = np.zeros(6)    # 关节速度
        self.alpha = 0.1                  # 滤波系数，可调整

        self.arm_controller.openGripper()
        time.sleep(2)
        print("右臂控制器初始化完成")

        # 3. 第一次获取机械臂状态，确保连接正常
        self.positions_controller = self.arm_controller.get_joint_positions()
        self.positions_follower = self.arm_follower.get_joint_positions()
        self.positions_controller_gripper = self.arm_controller.get_gripper_position()
        self.positions_follower_gripper = self.arm_follower.get_gripper_position()
        print("右臂初始状态获取完成")

        # 4. 创建关节状态发布者
        self.joint_pub_controller = self.create_publisher(JointState, '/left_arm/joint_states_target', 10)
        self.joint_pub_follower = self.create_publisher(JointState, '/left_arm/joint_states_now', 10)
        print("话题初始化完成")

        # 5. 初始化并启动线程
        self.state_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.gravity_thread = threading.Thread(target=self.gravity, daemon=True)
        self.gravity_thread.start() # 启动线程
        print("重力补偿独立线程已启动")
        self.control_thread = threading.Thread(target=self.control, daemon=True)
        self.control_thread.start() # 启动线程
        print("控制独立线程已启动")
        # self.gripper_thread = threading.Thread(target=self.gripper, daemon=True)
        # self.gripper_thread.start() # 启动线程
        # print("夹持器独立线程已启动")
        self.publish_thread = threading.Thread(target=self.publish_joint_states, daemon=True)
        self.publish_thread.start() # 启动线程
        print("发布关节线程已启动")

    def publish_joint_states(self):
        try:
            while not self.stop_event.is_set():
                # 1. 检查关节数量是否匹配（避免发布错误数据）
                with self.state_lock:
                    temp_controller = np.append(self.positions_controller, self.positions_controller_gripper)
                    temp_follower = np.append(self.positions_follower, self.positions_follower_gripper)
                if len(temp_controller) != len(self.joint_names):
                    print(f"主臂关节数量不匹配：读取到{len(self.positions_controller)}个关节，预期{len(self.joint_names)}个")
                    return
                if len(temp_follower) != len(self.joint_names):
                    print(f"从臂关节数量不匹配：读取到{len(self.positions_follower)}个关节，预期{len(self.joint_names)}个")
                    return
                # 2. 构建JointState消息
                joint_msg_controller = JointState()
                joint_msg_controller.header.stamp = self.get_clock().now().to_msg()  # 时间戳
                joint_msg_controller.name = self.joint_names  # 关节名称列表
                joint_msg_controller.position = [float(x) for x in temp_controller]  # 关节位置（弧度或角度，取决于硬件）

                joint_msg_follower = JointState()
                joint_msg_follower.header.stamp = self.get_clock().now().to_msg()  # 时间戳
                joint_msg_follower.name = self.joint_names  # 关节名称列表
                joint_msg_follower.position = [float(x) for x in temp_follower]  # 关节位置（弧度或角度，取决于硬件）

                # 5. 发布消息
                self.joint_pub_controller.publish(joint_msg_controller)
                self.joint_pub_follower.publish(joint_msg_follower)
                time.sleep(0.01)
        except Exception as e:
            print(f"发布关节状态失败: {str(e)}")

    def gravity(self):
        while not self.stop_event.is_set():
            try:
                self.arm_controller.gravity_compensation()
                time.sleep(0.01)
            except Exception as e:
                if self.stop_event.is_set():
                    break
                print(f"右重力补偿独立线程执行失败: {str(e)}")
                time.sleep(0.1)  # 避免过快循环导致日志刷屏

    def control(self):
        while not self.stop_event.is_set():
            try:
                with self.state_lock:
                    self.positions_controller = self.arm_controller.get_joint_positions()
                    velocities_controller_raw = self.arm_controller.get_joint_velocities()

                    # 一阶低通滤波
                    self.vel_filtered = (
                        self.alpha * velocities_controller_raw 
                        + (1 - self.alpha) * self.vel_filtered
                    )
                    self.positions_follower = self.arm_follower.get_joint_positions()
                    temp_positions_controller = self.positions_controller

                    #手指
                    self.positions_controller_gripper = self.arm_controller.get_gripper_position()
                    self.positions_follower_gripper = self.arm_follower.get_gripper_position()
                    temp_positions_controller_gripper = self.positions_controller_gripper

                # 使用滤波后的速度
                self.arm_follower.set_joint_raw(positions=temp_positions_controller,velocities=self.vel_filtered)
                self.arm_follower.setGripperPosition(position = temp_positions_controller_gripper)

                time.sleep(0.001)
            except Exception as e:
                if self.stop_event.is_set():
                    break
                print(f"右臂控制独立线程执行失败: {str(e)}")
                time.sleep(0.1)  # 避免过快循环导致日志刷屏

    def shutdown(self):
        self.stop_event.set()

        for thread in [self.gravity_thread, self.control_thread, self.publish_thread]:
            if thread.is_alive():
                thread.join(timeout=1.0)

        for arm, name in [(self.arm_controller, "can0"), (self.arm_follower, "can1")]:
            try:
                arm.cleanup()
                print(f"{name} cleanup ok")
            except Exception as e:
                print(f"{name} cleanup failed: {str(e)}")
                
def main(args=None):
    # 初始化ROS 2
    rclpy.init(args=args)
    
    # 创建并运行节点
    node = MainArmJointPublisher()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # 清理资源
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
