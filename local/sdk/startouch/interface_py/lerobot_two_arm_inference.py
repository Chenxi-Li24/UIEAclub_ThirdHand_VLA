import time
import rclpy
import threading
import numpy as np
from rclpy.node import Node
from sensor_msgs.msg import JointState
from startouchclass import SingleArm  # 导入你的主臂控制类

class MainArmJointInference(Node):
    def __init__(self):
        super().__init__('main_arm_joint_inference')

        # 1. 定义关节名称
        self.joint_names = ["left_shoulder_pan", "left_shoulder_lift", "left_elbow_flex", "left_wrist_1", "left_wrist_2", "left_wrist_3", "left_gripper", 
                            "right_shoulder_pan", "right_shoulder_lift", "right_elbow_flex", "right_wrist_1", "right_wrist_2", "right_wrist_3", "right_gripper"]

        # 2. 初始化主臂控制器
        self.arm_right = SingleArm(can_interface_="can0", enable_fd_=False)
        self.arm_left = SingleArm(can_interface_="can1", enable_fd_=False)
        time.sleep(2)

        # 3. 第一次获取机械臂状态，确保连接正常
        self.positions_right_target = self.arm_right.get_joint_positions()
        self.positions_left_target = self.arm_left.get_joint_positions()
        self.gripper_right_target = 0.25
        self.gripper_left_target = 0.25
        print("从臂初始状态获取完成")

        # 4. 创建关节状态发布者和订阅者
        self.joint_positions_pub = self.create_publisher(JointState, '/puppet/joint', 10)
        self.joint_positions_sub = self.create_subscription(JointState, '/master/joint', self.process_joint_state, 10)
        print("话题初始化完成")

        # 5. 初始化并启动线程
        self.target_lock = threading.Lock()
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
            while True:
                # 2. 构建JointState消息
                temp_right = np.append(self.arm_right.get_joint_positions(), self.arm_right.get_gripper_position())
                temp_left = np.append(self.arm_left.get_joint_positions(), self.arm_left.get_gripper_position())
                temp = np.append(temp_left, temp_right)
                joint_state_msg = JointState()
                joint_state_msg.header.stamp = self.get_clock().now().to_msg()  # 时间戳
                joint_state_msg.name = self.joint_names  # 关节名称列表
                joint_state_msg.position = [float(x) for x in temp]  # 关节位置（弧度或角度，取决于硬件）

                # 3. 发布消息
                self.joint_positions_pub.publish(joint_state_msg)
                time.sleep(0.005)
        except Exception as e:
            print(f"发布关节状态失败: {str(e)}")
    
    def process_joint_state(self, msg: JointState):
        try:
            with self.target_lock:
                # 1. 提取右臂关节位置
                right_positions = []
                for joint_name in ["right_shoulder_pan", "right_shoulder_lift", "right_elbow_flex", "right_wrist_1", "right_wrist_2", "right_wrist_3"]:
                    if joint_name in msg.name:
                        right_positions.append(msg.position[msg.name.index(joint_name)])
                self.positions_right_target = right_positions
                if "right_gripper" in msg.name:
                    self.gripper_right_target = msg.position[msg.name.index("right_gripper")]

                # 2. 提取左臂关节位置
                left_positions = []
                for joint_name in ["left_shoulder_pan", "left_shoulder_lift", "left_elbow_flex", "left_wrist_1", "left_wrist_2", "left_wrist_3"]:
                    if joint_name in msg.name:
                        left_positions.append(msg.position[msg.name.index(joint_name)])
                self.positions_left_target = left_positions
                if "left_gripper" in msg.name:
                    self.gripper_left_target = msg.position[msg.name.index("left_gripper")]
        except Exception as e:
            print(f"处理接收到的关节状态失败: {str(e)}")

    def control(self):
        while True:
            try:
                with self.target_lock:
                    right_target = list(self.positions_right_target)
                    left_target = list(self.positions_left_target)

                    right_gripper = self.gripper_right_target
                    left_gripper = self.gripper_left_target
                # self.arm_right.setGripperPosition(position = right_gripper)
                # self.arm_left.setGripperPosition(position = left_gripper)

                # self.arm_right.set_joint_raw(positions = right_target, velocities = [0, 0, 0, 0, 0, 0])
                # self.arm_left.set_joint_raw(positions = left_target, velocities = [0, 0, 0, 0, 0, 0])
                time.sleep(0.001)
            except Exception as e:
                print(f"双臂控制独立线程执行失败: {str(e)}")
                time.sleep(0.1)  # 避免过快循环导致日志刷屏

def main(args=None):
    # 初始化ROS 2
    rclpy.init(args=args)
    
    # 创建并运行节点
    node = MainArmJointInference()
    
    try:
        rclpy.spin(node)
    finally:
        # 清理资源
        node.arm_right.arm.cleanup()
        node.arm_left.arm.cleanup()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
