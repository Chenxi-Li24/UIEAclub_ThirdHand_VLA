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
        self.arm_controller_right = SingleArm(can_interface_="can0", enable_fd_=False)
        time.sleep(2)
        
        self.vel_filtered = np.zeros(6)    # 关节速度
        self.alpha = 0.1                  # 滤波系数，可调整
        print("右臂控制器初始化完成")

        # 3. 第一次获取机械臂状态，确保连接正常
        # 存储当前关节，
        self.positions_follower = self.arm_controller_right.get_joint_positions()
        self.positions_follower_gripper = self.arm_controller_right.get_gripper_position()

        # 存储上一时刻机械臂的关节状态作为target关节
        self.positions_pre = self.positions_follower
        self.positions_gripper_pre = self.positions_follower_gripper


        print("右臂初始状态获取完成")

        # 4. 创建关节状态发布者
        self.joint_pub_controller = self.create_publisher(JointState, '/right_arm/joint_states_target', 10)
        self.joint_pub_follower = self.create_publisher(JointState, '/right_arm/joint_states_now', 10)
        print("话题初始化完成")

        # 5. 初始化并启动线程
        self.state_lock = threading.Lock()
        self.gravity_thread = threading.Thread(target=self.gravity, daemon=True)
        self.gravity_thread.start() # 启动线程
        print("重力补偿独立线程已启动")
        self.publish_thread = threading.Thread(target=self.publish_joint_states, daemon=True)
        self.publish_thread.start() # 启动线程
        print("发布关节线程已启动")

    def publish_joint_states(self):
        try:
            while True:
                # 1. 检查关节数量是否匹配（避免发布错误数据）
                with self.state_lock:
                    self.positions_follower = self.arm_controller_right.get_joint_positions()
                    self.positions_follower_gripper = self.arm_controller_right.get_gripper_position()

                    # temp_controller = np.append(self.positions_controller, self.positions_controller_gripper)
                    temp_follower = np.append(self.positions_follower, self.positions_follower_gripper)
                    temp_controller = np.append(self.positions_pre, self.positions_gripper_pre)

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

                # 更新上一时刻的关节
                self.positions_pre = self.positions_follower
                self.positions_gripper_pre = self.positions_follower_gripper


                time.sleep(0.01)
        except Exception as e:
            print(f"发布关节状态失败: {str(e)}")

    def gravity(self):
        while True:
            try:
                self.arm_controller_right.gravity_compensation()
                time.sleep(0.01)
            except Exception as e:
                print(f"右重力补偿独立线程执行失败: {str(e)}")
                time.sleep(0.1)  # 避免过快循环导致日志刷屏

def main(args=None):
    # 初始化ROS 2
    rclpy.init(args=args)
    
    # 创建并运行节点
    node = MainArmJointPublisher()
    
    try:
        rclpy.spin(node)
    finally:
        # 清理资源
        node.arm_controller_right.arm.cleanup()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()