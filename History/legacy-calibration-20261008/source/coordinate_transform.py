"""
坐标变换工具
  旋转: 旋转矩阵 ↔ 旋转向量(Rodrigues) ↔ 四元数 ↔ 欧拉角
  齐次变换: 4×4 变换矩阵的合成、求逆、应用

应用场景:
  - T_base_camera: 相机在机械臂基座坐标系中的位姿
  - T_camera_obj: 目标在相机坐标系中的位姿 (由 ArUco/solvePnP 得到)
  - T_base_obj = T_base_camera @ T_camera_obj (目标在基座坐标系中的位姿)
"""

import numpy as np
from scipy.spatial.transform import Rotation as R


def rotmat_from_rvec(rvec):
    """旋转向量 (Rodrigues) → 3×3 旋转矩阵"""
    return R.from_rotvec(rvec.flatten()).as_matrix()


def rvec_from_rotmat(rotmat):
    """3×3 旋转矩阵 → 旋转向量 (Rodrigues)"""
    return R.from_matrix(rotmat).as_rotvec()


def rotmat_from_quat(quat_xyzw):
    """四元数 (x, y, z, w) → 3×3 旋转矩阵"""
    return R.from_quat(quat_xyzw).as_matrix()


def quat_from_rotmat(rotmat):
    """3×3 旋转矩阵 → 四元数 (x, y, z, w)"""
    return R.from_matrix(rotmat).as_quat()


def rotmat_from_euler(roll, pitch, yaw, degrees=True):
    """欧拉角 (roll, pitch, yaw) → 3×3 旋转矩阵 (内旋 ZYX)"""
    return R.from_euler('zyx', [yaw, pitch, roll], degrees=degrees).as_matrix()


def euler_from_rotmat(rotmat, degrees=True):
    """3×3 旋转矩阵 → 欧拉角 (roll, pitch, yaw) (内旋 ZYX)"""
    euler = R.from_matrix(rotmat).as_euler('zyx', degrees=degrees)
    return euler[2], euler[1], euler[0]  # roll, pitch, yaw


# ============================================================
# 齐次变换矩阵
# ============================================================

def pose_from_rvec_tvec(rvec, tvec):
    """
    旋转向量 + 平移向量 → 4×4 齐次变换矩阵
    """
    T = np.eye(4)
    T[:3, :3] = rotmat_from_rvec(rvec)
    T[:3, 3] = tvec.flatten()
    return T


def pose_from_quat_tvec(quat_xyzw, tvec):
    """
    四元数 + 平移向量 → 4×4 齐次变换矩阵
    """
    T = np.eye(4)
    T[:3, :3] = rotmat_from_quat(quat_xyzw)
    T[:3, 3] = tvec.flatten()
    return T


def rvec_tvec_from_pose(T):
    """4×4 齐次变换矩阵 → (旋转向量, 平移向量)"""
    rvec = rvec_from_rotmat(T[:3, :3])
    tvec = T[:3, 3].reshape(3, 1)
    return rvec, tvec


def invert_pose(T):
    """求齐次变换矩阵的逆"""
    T_inv = np.eye(4)
    R = T[:3, :3]
    t = T[:3, 3]
    T_inv[:3, :3] = R.T
    T_inv[:3, 3] = -R.T @ t
    return T_inv


def apply_transform(T, points):
    """
    将 4×4 变换应用到 3D 点集
    points: (N, 3) 或 (3,)
    返回: 变换后的点
    """
    points = np.atleast_2d(points)
    N = points.shape[0]
    homogeneous = np.hstack([points, np.ones((N, 1))])
    transformed = (T @ homogeneous.T).T
    return transformed[:, :3].squeeze()


# ============================================================
# Eye-to-Hand 标定 (相机固定在外部，观察机械臂上的 marker)
# ============================================================

def calibrate_eye_to_hand(T_base_ee_list, T_camera_marker_list):
    """
    Eye-to-Hand 手眼标定

    T_base_ee: 机械臂末端在基座坐标系中的位姿列表
    T_camera_marker: Marker 在相机坐标系中的位姿列表
                    (每个是 ArUco solvePnP 的逆, 即 T_camera_marker)

    原理: T_base_camera 是未知常数
      T_base_marker = T_base_ee @ T_ee_marker     (通过机械臂)
      T_base_marker = T_base_camera @ T_camera_marker  (通过相机)
      → T_base_ee @ T_ee_marker = T_base_camera @ T_camera_marker
      → T_base_camera @ T_camera_marker @ inv(T_ee_marker) = T_base_ee

    如果 marker 固定在机械臂末端 (T_ee_marker 已知):
      → 这是 Eye-to-Hand 标准问题

    OpenCV calibrateHandEye 接口:
      R_base_camera, t_base_camera = calibrateHandEye(
          R_ee_base_list, t_ee_base_list,    # 机械臂末端在 base 中的位姿
          R_marker_camera_list, t_marker_camera_list  # marker 在相机中的位姿
      )

    返回: T_base_camera (4×4), 相机在机械臂基座坐标系中的位姿
    """
    if len(T_base_ee_list) != len(T_camera_marker_list):
        raise ValueError("位姿列表长度不一致")
    if len(T_base_ee_list) < 3:
        raise ValueError(f"至少需要 3 组数据, 当前 {len(T_base_ee_list)} 组")

    R_ee_base_list = []
    t_ee_base_list = []
    R_marker_camera_list = []
    t_marker_camera_list = []

    for T_base_ee, T_camera_marker in zip(T_base_ee_list, T_camera_marker_list):
        # 机械臂: R_ee_base, t_ee_base (末端在基座中)
        R_ee_base = T_base_ee[:3, :3]
        t_ee_base = T_base_ee[:3, 3].reshape(3, 1)
        R_ee_base_list.append(R_ee_base)
        t_ee_base_list.append(t_ee_base)

        # 相机: R_marker_camera, t_marker_camera (marker 在相机中)
        R_marker_camera = T_camera_marker[:3, :3]
        t_marker_camera = T_camera_marker[:3, 3].reshape(3, 1)
        R_marker_camera_list.append(R_marker_camera)
        t_marker_camera_list.append(t_marker_camera)

    # OpenCV 手眼标定
    R_base_camera, t_base_camera = cv2.calibrateHandEye(
        R_ee_base_list, t_ee_base_list,
        R_marker_camera_list, t_marker_camera_list,
        method=cv2.CALIB_HAND_EYE_TSAI
    )

    T_base_camera = np.eye(4)
    T_base_camera[:3, :3] = R_base_camera
    T_base_camera[:3, 3] = t_base_camera.flatten()

    return T_base_camera


# ============================================================
# Robot-World/Hand-Eye 标定
# ============================================================

def calibrate_robot_world_hand_eye(
    T_world_ee_list, T_camera_marker_list
):
    """
    Robot-World/Hand-Eye 联合标定
    T_world_ee: 末端在世界坐标系中的位姿
    T_camera_marker: marker 在相机中的位姿

    返回: (T_world_camera, T_ee_marker)
    """
    R_world_ee_list = [T[:3, :3] for T in T_world_ee_list]
    t_world_ee_list = [T[:3, 3].reshape(3, 1) for T in T_world_ee_list]
    R_marker_camera_list = [T[:3, :3] for T in T_camera_marker_list]
    t_marker_camera_list = [T[:3, 3].reshape(3, 1) for T in T_camera_marker_list]

    R_world_camera, t_world_camera, R_ee_marker, t_ee_marker = \
        cv2.calibrateRobotWorldHandEye(
            R_world_ee_list, t_world_ee_list,
            R_marker_camera_list, t_marker_camera_list,
        )

    T_world_camera = np.eye(4)
    T_world_camera[:3, :3] = R_world_camera
    T_world_camera[:3, 3] = t_world_camera.flatten()

    T_ee_marker = np.eye(4)
    T_ee_marker[:3, :3] = R_ee_marker
    T_ee_marker[:3, 3] = t_ee_marker.flatten()

    return T_world_camera, T_ee_marker


# ============================================================
# 工具函数
# ============================================================

def print_pose(T, name="T"):
    """打印齐次变换矩阵"""
    r, p, y = euler_from_rotmat(T[:3, :3])
    t = T[:3, 3]
    print(f"{name}:")
    print(f"  RPY (deg): roll={r:.2f}, pitch={p:.2f}, yaw={y:.2f}")
    print(f"  XYZ (m):   x={t[0]:.4f}, y={t[1]:.4f}, z={t[2]:.4f}")


def average_poses(pose_list):
    """对多个位姿求平均 (平移取均值, 旋转用四元数平均)"""
    if len(pose_list) == 0:
        return np.eye(4)

    # 平移平均
    t_avg = np.mean([T[:3, 3] for T in pose_list], axis=0)

    # 旋转用四元数平均
    quats = np.array([quat_from_rotmat(T[:3, :3]) for T in pose_list])
    # 四元数符号一致性处理
    for i in range(1, len(quats)):
        if np.dot(quats[0], quats[i]) < 0:
            quats[i] = -quats[i]
    q_avg = np.mean(quats, axis=0)
    q_avg /= np.linalg.norm(q_avg)

    T_avg = np.eye(4)
    T_avg[:3, :3] = rotmat_from_quat(q_avg)
    T_avg[:3, 3] = t_avg

    return T_avg


if __name__ == "__main__":
    # 测试
    print("=== 坐标变换工具测试 ===")

    # 创建测试变换
    T_test = np.eye(4)
    T_test[:3, :3] = rotmat_from_euler(10, 20, 30)
    T_test[:3, 3] = [0.5, 0.3, 1.2]

    print_pose(T_test, "测试变换")

    # 逆变换
    T_inv = invert_pose(T_test)
    print_pose(T_inv, "逆变换")

    # 验证
    T_identity = T_test @ T_inv
    print(f"\nT @ inv(T) 接近 I: {np.allclose(T_identity, np.eye(4), atol=1e-10)}")

    # 应用变换
    pt = np.array([1.0, 0.0, 0.0])
    pt_transformed = apply_transform(T_test, pt)
    print(f"点 {pt} 变换后: {pt_transformed}")
