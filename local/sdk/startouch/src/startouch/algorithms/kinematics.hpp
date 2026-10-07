#pragma once

#include <algorithm>
#include <Eigen/Dense>      // 提供 Eigen::Vector3d, Matrix3d, Matrix4d 等
#include <cmath>            // 提供 std::sin, std::cos, std::tanh, std::abs, std::asin, std::atan2
#include <vector>          // 提供 std::vector
#include <utility>

#include <memory>
#include <kdl/chain.hpp>
#include <kdl/chaindynparam.hpp>
#include <kdl/chainfksolverpos_recursive.hpp>
#include <kdl/chainiksolverpos_lma.hpp>
#include <kdl/chainiksolvervel_pinv.hpp>
#include <kdl/frames.hpp>


using vec3 = Eigen::Vector3d;
using vec4 = Eigen::Vector4d;
using vec6 = Eigen::Matrix<double, 6, 1>;
using mat3 = Eigen::Matrix3d;
using mat4 = Eigen::Matrix4d;

inline constexpr double pi = M_PI;

inline mat3 skew(const vec3& w) {
    mat3 w_hat;
    w_hat <<     0, -w(2),  w(1),
              w(2),     0, -w(0),
             -w(1),  w(0),     0;
    return w_hat;
}

inline mat4 t_from_xyzrpy(const vec3& xyz, const vec3& rpy) {
    mat4 t = mat4::Identity();
    double cx = cos(rpy(0)), sx = sin(rpy(0));
    double cy = cos(rpy(1)), sy = sin(rpy(1));
    double cz = cos(rpy(2)), sz = sin(rpy(2));

    mat3 rx, ry, rz;
    rx << 1, 0, 0,
          0, cx, -sx,
          0, sx,  cx;

    ry <<  cy, 0, sy,
           0,  1, 0,
         -sy, 0, cy;

    rz << cz, -sz, 0,
          sz,  cz, 0,
          0,   0,  1;

    t.block<3,3>(0,0) = rz * ry * rx;
    t.block<3,1>(0,3) = xyz;
    return t;
}

inline mat3 exp_so3(const vec3& w, double theta) {
    double n = w.norm();
    if (n < 1e-12) return mat3::Identity();
    vec3 wn = w / n;
    mat3 w_hat = skew(wn);
    double th = theta * n;
    return mat3::Identity() + sin(th)*w_hat + (1 - cos(th))*(w_hat * w_hat);
}

inline mat4 exp_se3(const vec6& s, double theta) {
    vec3 w = s.head<3>(), v = s.tail<3>();
    double n = w.norm();
    mat4 t = mat4::Identity();
    if (n < 1e-12) {
        t.block<3,1>(0,3) = v * theta;
        return t;
    }
    vec3 wn = w / n;
    mat3 w_hat = skew(wn);
    mat3 r = exp_so3(wn, theta);
    double th = theta;
    mat3 v_mat = th * mat3::Identity() + (1 - cos(th)) * w_hat + (th - sin(th)) * w_hat * w_hat;
    t.block<3,3>(0,0) = r;
    t.block<3,1>(0,3) = v_mat * v;
    return t;
}


using namespace KDL;

// 类声明
class RobotKinematics {
    public:
        struct joint_t {
            std::string name;
            vec3 xyz;
            vec3 rpy;
            vec3 axis;
        };

        std::vector<joint_t> joints_;
        vec3 tool_xyz_, tool_rpy_;
        std::vector<vec6> screw_axes_;
        std::vector<vec3> omega_list_, q_list_;
        std::vector<double> joint_lower_limits_;
        std::vector<double> joint_upper_limits_;
        std::vector<bool> joint_has_position_limits_;
        mat4 m_;
        size_t n_joints_;
        
        RobotKinematics();  // 构造函数声明
        ~RobotKinematics(); // 析构函数声明
        void build_screw_axes();
        mat4 forward_kinematics(const Eigen::VectorXd& joint_angles) const;
        vec3 rotation_matrix_to_euler(const mat3& r) const ;
        vec4 rotation_matrix_to_quaternion(const mat3& r) const;
        vec3 quaternion_error(const vec4& q_target, const vec4& q_current) const;
        std::pair<Eigen::VectorXd, bool> inverse_kinematics_jacobian(
            const vec3& target_pos, const vec3& target_euler,
            const Eigen::VectorXd& initial_guess, double threshold_pos = 0.01,
            double threshold_rot = 0.05, int max_iterations = 50, double damping = 0.005) ;


        //kdl
        bool solve_ik_kdl(const std::vector<double>& target_pos, 
                    const std::vector<double>& target_euler, 
                    const std::vector<double>& q_curr_vec,
                    std::vector<double>& q_out,
                    bool* used_fallback = nullptr);
        std::vector<double> forwardKinematics_kdl(const std::vector<double>& q_vec);
        std::vector<double> gravity_compensation_kdl(const std::vector<double>& q_vec) const;
        std::vector<double> coriolis_compensation_kdl(const std::vector<double>& q_vec,const std::vector<double>& qd_vec) const;
        std::vector<double> inertia_compensation_kdl(const std::vector<double>& q_vec,const std::vector<double>& qdd_vec) const;

        std::vector<double> dynamic_compensation_kdl(
                const std::vector<double>& q_vec, 
                const std::vector<double>& qd_vec, 
                const std::vector<double>& qdd_vec) const;


    private:
        int num_joints_;
        // 成员变量
        Chain chain;
        std::unique_ptr<ChainIkSolverPos_LMA> ik_solver_;
        std::unique_ptr<ChainFkSolverPos_recursive> fk_solver_;
        std::unique_ptr<ChainDynParam> dyn_solver_;

};


