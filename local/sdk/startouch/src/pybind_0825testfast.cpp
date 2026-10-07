#include <pybind11/pybind11.h>
#include <pybind11/stl.h>  // 支持 std::vector 到 Python list 的转换
#include <pybind11/eigen.h>  // 支持 Eigen 矩阵到 Python 的转换
#include <pybind11/functional.h>
// #include "startouch/algorithms/interfaces_simpletest_wopin.hpp" 
#include "startouch/algorithms/interfaces_0825fasttest.hpp" 

namespace py = pybind11;
PYBIND11_MODULE(startouch, m) {
    // SDK version note: 2026-06-05, author Charlie.
    m.attr("__version__") = "0.1.7";

    py::class_<ArmController::MotionProgramItem>(m, "MotionProgramItem")
        .def(py::init<>())
        .def_readwrite("type", &ArmController::MotionProgramItem::type)
        .def_readwrite("waypoints", &ArmController::MotionProgramItem::waypoints)
        .def_readwrite("poses", &ArmController::MotionProgramItem::poses)
        .def_readwrite("time_sec", &ArmController::MotionProgramItem::time_sec)
        .def_readwrite("speed_percent", &ArmController::MotionProgramItem::speed_percent)
        .def_readwrite("sleep_sec", &ArmController::MotionProgramItem::sleep_sec)
        .def_readwrite("blend_radius_m", &ArmController::MotionProgramItem::blend_radius_m);

    py::class_<ArmController>(m, "ArmController")
        .def(py::init([](py::kwargs kwargs) {
        //std::string permutation_matrix = kwargs.contains("permutation_matrix") ? kwargs["permutation_matrix"].cast<std::string>() : "/media/sdk/data/aproject/Xrobot/Nxyarm/openarm_can/param_csv/permutationMatrix.csv";
        //std::string pi_b = kwargs.contains("pi_b") ? kwargs["pi_b"].cast<std::string>() : "/media/sdk/data/aproject/Xrobot/Nxyarm/openarm_can/param_csv/pi_b.csv";
        //std::string pi_fr = kwargs.contains("pi_fr") ? kwargs["pi_fr"].cast<std::string>() : "/media/sdk/data/aproject/Xrobot/Nxyarm/openarm_can/param_csv/pi_fr.csv";   
        bool gripper_exist = kwargs.contains("gripper_exist") ? kwargs["gripper_exist"].cast<bool>() : false;
        std::string can_interface = kwargs.contains("can_interface") ? kwargs["can_interface"].cast<std::string>() : "can0";
            bool enable_fd = kwargs.contains("enable_fd") ? kwargs["enable_fd"].cast<bool>() : false;
            bool dry_run = kwargs.contains("dry_run") ? kwargs["dry_run"].cast<bool>() : false;
            return new ArmController(gripper_exist,can_interface, enable_fd,
                                     startouch::damiao_motor::ControlMode::MIT_MODE,
                                     dry_run);
        }))

        // .def("printConfig", &ArmController::printConfig,"A function which queries the initial params configuration of the arm controller.")
        .def("set_joint", &ArmController::set_joint, 
            "Set the target joint positions with a given time duration.\n"
            "Parameters:\n"
            "  q_end (list of float): The target joint angles.\n"
            "  tf (float): The time duration to reach the target positions.",
            py::arg("q_end"), py::arg("tf") = 4.0)

        .def("set_joint_raw", &ArmController::set_joint_raw,py::arg("q_end"),py::arg("v_end"))

        .def("move_joint_waypoints", &ArmController::move_joint_waypoints,
            "Move through joint waypoints with YAML-configured trajectory limits.\n"
            "Use either speed_percent in (0, 1] or time_sec > 0, not both. "
            "If neither is provided, speed_percent=0.1 is used. "
            "Blocks until the motion finishes and returns the planned motion duration in seconds.",
            py::arg("waypoints"),
            py::arg("time_sec") = 0.0,
            py::arg("speed_percent") = -1.0,
            py::call_guard<py::gil_scoped_release>())

        .def("move_joint_waypoints_with_gripper", &ArmController::move_joint_waypoints_with_gripper,
            "Move through joint waypoints and synchronize gripper targets to the same "
            "planned waypoint trajectory. gripper_positions must have one value per waypoint.",
            py::arg("waypoints"),
            py::arg("gripper_positions"),
            py::arg("time_sec") = 0.0,
            py::arg("speed_percent") = -1.0,
            py::call_guard<py::gil_scoped_release>())

        .def("update_joint_waypoint_chunk", &ArmController::update_joint_waypoint_chunk,
            "Joint waypoint action chunk update. Non-blocking: keeps a short prefix of the active "
            "waypoint trajectory, appends a freshly planned suffix, and replaces future samples.",
            py::arg("waypoints"),
            py::arg("time_sec") = 0.0,
            py::arg("speed_percent") = -1.0,
            py::arg("switch_delay_sec") = 0.05,
            py::call_guard<py::gil_scoped_release>())

        .def("update_joint_waypoint_chunk_with_gripper", &ArmController::update_joint_waypoint_chunk_with_gripper,
            "Joint waypoint action chunk update with synchronized gripper targets. Non-blocking; "
            "gripper_positions must have one value per waypoint.",
            py::arg("waypoints"),
            py::arg("gripper_positions"),
            py::arg("time_sec") = 0.0,
            py::arg("speed_percent") = -1.0,
            py::arg("switch_delay_sec") = 0.05,
            py::call_guard<py::gil_scoped_release>())

        .def("plan_joint_waypoints_with_gripper", &ArmController::plan_joint_waypoints_with_gripper,
            "Dry-run plan joint waypoints with synchronized gripper targets without publishing. "
            "Rows are [t_rel, q1..q6, x, y, z, roll, pitch, yaw, gripper, planning_time_s].",
            py::arg("q_start"),
            py::arg("waypoints"),
            py::arg("gripper_positions"),
            py::arg("time_sec") = 0.0,
            py::arg("speed_percent") = -1.0,
            py::call_guard<py::gil_scoped_release>())

        .def("move_l", &ArmController::move_l,
            "MoveL: execute Cartesian linear pose waypoints. Pose format is "
            "[x, y, z, roll, pitch, yaw]. Orientation interpolation uses quaternion slerp.",
            py::arg("poses"),
            py::arg("time_sec") = 0.0,
            py::arg("speed_percent") = -1.0,
            py::arg("blend_radius_m") = 0.0,
            py::arg("position_tolerance_m") = 0.003,
            py::arg("orientation_tolerance_rad") = 0.05,
            py::call_guard<py::gil_scoped_release>())

        .def("move_p", &ArmController::move_p,
            "MoveP: execute Cartesian pose waypoints with corner blending. Pose format is "
            "[x, y, z, roll, pitch, yaw]. Orientation interpolation uses quaternion slerp.",
            py::arg("poses"),
            py::arg("time_sec") = 0.0,
            py::arg("speed_percent") = -1.0,
            py::arg("blend_radius_m") = 0.002,
            py::arg("position_tolerance_m") = 0.003,
            py::arg("orientation_tolerance_rad") = 0.05,
            py::call_guard<py::gil_scoped_release>())

        .def("move_p_with_gripper", &ArmController::move_p_with_gripper,
            "MoveP with synchronized gripper targets. Pose format is "
            "[x, y, z, roll, pitch, yaw]; gripper_positions must have one value per input pose.",
            py::arg("poses"),
            py::arg("gripper_positions"),
            py::arg("time_sec") = 0.0,
            py::arg("speed_percent") = -1.0,
            py::arg("blend_radius_m") = 0.002,
            py::arg("position_tolerance_m") = 0.003,
            py::arg("orientation_tolerance_rad") = 0.05,
            py::call_guard<py::gil_scoped_release>())

        .def("get_last_waypoint_command_samples", &ArmController::get_last_waypoint_command_samples,
            "Return the last planned waypoint command samples. Rows are "
            "[t_rel, q1..q6, x, y, z, roll, pitch, yaw, gripper, planning_time_s].")

        .def("run_motion_program", &ArmController::run_motion_program,
            "Run a structured motion program. Consecutive MoveJ items are merged "
            "for continuous waypoint planning; Sleep items are blocking breakpoints.",
            py::arg("program"),
            py::call_guard<py::gil_scoped_release>())

        .def("gravity_compensation", &ArmController::identify_gravity_compensation,"identify_gravity_compensation function.")        
        
        .def("set_end_effector_pose", &ArmController::set_end_effector_pose, 
            "Set the end effector's target pose.\n"
            "\n"
            "This function sets the target position and orientation (pose) for the end effector. "
            "The target position is specified by the `target_pos` vector, and the target orientation "
            "is given by the Euler angles `target_euler`. The `tf` parameter defines the time to reach "
            "the target pose, with a default value of 4.0 seconds.\n"
            "\n"
            "Parameters:\n"
            "  target_pos (Eigen::Vector3d): Target position as a 3D vector (x, y, z).\n"
            "  target_euler (Eigen::Vector3d): Target orientation as Euler angles (roll, pitch, yaw).\n"
            "  tf (float, optional): Time to reach the target pose, in seconds. Default is 4.0.\n"
            , py::arg("target_pos"), py::arg("target_euler"), py::arg("tf") = 4.0)
        

        .def("set_end_effector_pose_raw", &ArmController::set_end_effector_pose_raw, 
            "Set the end effector's target pose.\n"
            "\n"
            "This function sets the target position and orientation (pose) for the end effector. "
            "The target position is specified by the `target_pos` vector, and the target orientation "
            "is given by the Euler angles `target_euler`. The `tf` parameter defines the time to reach "
            "\n"
            "Parameters:\n"
            "  target_pos (Eigen::Vector3d): Target position as a 3D vector (x, y, z).\n"
            "  target_euler (Eigen::Vector3d): Target orientation as Euler angles (roll, pitch, yaw).\n"
            , py::arg("target_pos"), py::arg("target_euler"))

        .def("solve_ik", &ArmController::solve_ik,
            "Solve IK for target end-effector pose.\n"
            "\n"
            "Parameters:\n"
            "  target_pos (list[float]): Target position [x, y, z].\n"
            "  target_euler (list[float]): Target euler [roll, pitch, yaw].\n"
            "  q_seed (list[float], optional): IK initial seed, length=6. If empty, uses current joint.\n"
            "\n"
            "Returns:\n"
            "  tuple[list[float], bool]: (q_sol, success)\n",
            py::arg("target_pos"),
            py::arg("target_euler"),
            py::arg("q_seed") = std::vector<double>{},
            py::call_guard<py::gil_scoped_release>())
            
            

        .def("get_end_effector_pose", &ArmController::get_end_effector_pose)
        .def("get_joint_positions", &ArmController::get_joint)
        .def("get_joint_velocities", &ArmController::get_joint_velocities)
        .def("get_joint_torques", &ArmController::get_joint_torques)
        .def("openGripper", &ArmController::openGripper)
        .def("closeGripper", &ArmController::closeGripper)
        .def("setGripperPosition", &ArmController::setGripperPosition,py::arg("position") )
        .def("setGripperDistance",
             py::overload_cast<double, double, double>(&ArmController::setGripperDistance),
             py::arg("distance"), py::arg("kp") = 8.0, py::arg("kd") = 0.1)
        .def("get_gripper_position", &ArmController::get_gripper_position)
        .def("get_gripper_distance", &ArmController::get_gripper_distance)
        .def("cleanup", &ArmController::cleanup,py::call_guard<py::gil_scoped_release>())
        ;
}
