#pragma once

#include <Eigen/Dense>      // 提供 Eigen::Vector3d, Matrix3d, Matrix4d 等
#include <vector>          // 提供 std::vector
#include <utility>
#include <memory>
#include <atomic>
#include <string>

#include "startouch/damiao_motor/dm_motor_constants.hpp"


class ArmController {
    public:
        struct MotionProgramItem {
            std::string type;
            std::vector<std::vector<double>> waypoints;
            std::vector<std::vector<double>> poses;
            double time_sec = 0.0;
            double speed_percent = -1.0;
            double sleep_sec = 0.0;
            double blend_radius_m = 0.002;
        };

        ArmController(
            bool  gripper_exist = false,
            const std::string& can_interface = "can0", 
            bool enable_fd = false,
            startouch::damiao_motor::ControlMode motor_control_mode =
                //startouch::damiao_motor::ControlMode::POS_VEL_MODE
                startouch::damiao_motor::ControlMode::MIT_MODE,
            bool dry_run = false
        );

        ~ArmController();
        void set_joint(const std::vector<double>& q_end, double tf = 3.0);
        void set_joint_raw(const std::vector<double>& q_end,const std::vector<double>& v_end);
        double move_joint_waypoints(
            const std::vector<std::vector<double>>& waypoints,
            double time_sec = 0.0,
            double speed_percent = -1.0);
        double move_joint_waypoints_with_gripper(
            const std::vector<std::vector<double>>& waypoints,
            const std::vector<double>& gripper_positions,
            double time_sec = 0.0,
            double speed_percent = -1.0);
        double update_joint_waypoint_chunk(
            const std::vector<std::vector<double>>& waypoints,
            double time_sec = 0.0,
            double speed_percent = -1.0,
            double switch_delay_sec = 0.05);
        double update_joint_waypoint_chunk_with_gripper(
            const std::vector<std::vector<double>>& waypoints,
            const std::vector<double>& gripper_positions,
            double time_sec = 0.0,
            double speed_percent = -1.0,
            double switch_delay_sec = 0.05);
        std::vector<std::vector<double>> plan_joint_waypoints_with_gripper(
            const std::vector<double>& q_start,
            const std::vector<std::vector<double>>& waypoints,
            const std::vector<double>& gripper_positions,
            double time_sec = 0.0,
            double speed_percent = -1.0);
        double move_pose_waypoints(
            const std::vector<std::vector<double>>& poses,
            double time_sec = 0.0,
            double speed_percent = -1.0,
            double position_tolerance_m = 0.005,
            double orientation_tolerance_rad = 0.05);
        double move_l(
            const std::vector<std::vector<double>>& poses,
            double time_sec = 0.0,
            double speed_percent = -1.0,
            double blend_radius_m = 0.0,
            double position_tolerance_m = 0.003,
            double orientation_tolerance_rad = 0.05);
        double move_p(
            const std::vector<std::vector<double>>& poses,
            double time_sec = 0.0,
            double speed_percent = -1.0,
            double blend_radius_m = 0.002,
            double position_tolerance_m = 0.003,
            double orientation_tolerance_rad = 0.05);
        double move_p_with_gripper(
            const std::vector<std::vector<double>>& poses,
            const std::vector<double>& gripper_positions,
            double time_sec = 0.0,
            double speed_percent = -1.0,
            double blend_radius_m = 0.002,
            double position_tolerance_m = 0.003,
            double orientation_tolerance_rad = 0.05);
        std::vector<std::vector<double>> get_last_waypoint_command_samples();
        double run_motion_program(const std::vector<MotionProgramItem>& program);

        // void set_joint_raw_ik(const std::vector<double>& q_end,const std::vector<double>& v_end, const std::vector<double>& q_now);
        void identify_gravity_compensation();
        void identify_gravity_compensation_kdl();
        void set_end_effector_pose(const std::vector<double>& target_pos, const std::vector<double>& target_euler ,double tf) ;
        void set_end_effector_pose_raw(const std::vector<double>& target_pos, const std::vector<double>& target_euler);
        std::pair<std::vector<double>, bool> solve_ik(
            const std::vector<double>& target_pos,
            const std::vector<double>& target_euler,
            const std::vector<double>& q_seed = {});
         
       

        std::pair<Eigen::Vector3d, Eigen::Vector3d> get_end_effector_pose();
        Eigen::VectorXd get_joint();
        Eigen::VectorXd get_joint_cached();
        Eigen::VectorXd get_joint_velocities();
        Eigen::VectorXd get_joint_velocities_cached();
        Eigen::VectorXd get_joint_torques();
        void openGripper();
        void closeGripper();
        void setGripperPosition_raw(double position);
        void setGripperPosition(double position);
        void setGripperDistance(double distance);
        void setGripperDistance(double distance, double kp, double kd = 0.1);
        double get_gripper_position();
        double get_gripper_distance();
        void cleanup();
    private:
        // 线程对象
        std::atomic<bool> closed{false};
        class Impl;  // 声明私有实现类
        std::unique_ptr<Impl> pimpl_;  // 私有实现的指针
    };
