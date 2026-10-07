#!/usr/bin/env python3
"""
双臂轨迹复现：从 replay_data 读取左右臂末端轨迹（xyz + 四元数）及夹爪数据，
仿照 rollout_Xarm_tcp_pro_dual_arm.py 的 xarm 控制逻辑进行复现。
轨迹格式：每行 timestamp x y z qx qy qz qw（xyz 单位米，四元数 scipy xyzw）
夹爪格式：left/right_clamp_data_tum.txt 每行 timestamp value（value 为 0~90，会映射为机械臂 255~0）
"""
import argparse
import time
import numpy as np
from scipy.spatial.transform import Rotation as R
from tqdm import tqdm
from xarm.wrapper import XArmAPI


def load_clamp_tum(path):
    """加载夹爪 TUM 文件，每行 timestamp value，返回 (timestamps, values) 数组"""
    ts, vals = [], []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                ts.append(float(parts[0]))
                vals.append(float(parts[1]))
    return np.array(ts), np.array(vals) if ts else (np.array([]), np.array([]))


def align_clamp_to_trajectory(traj_timestamps, clamp_ts, clamp_vals, clamp_max=90):
    """
    按时间戳将夹爪序列对齐到轨迹步：对每个轨迹时间戳取最近邻夹爪值。
    夹爪数据范围为 0~clamp_max（默认 0~90），映射为机械臂控制 255~0（反向）。
    返回机械臂控制值 0~255，若无夹爪数据则返回 None（调用方用默认值）。
    """
    if len(clamp_ts) == 0 or len(clamp_vals) == 0:
        return None
    idx = np.argmin(np.abs(clamp_ts[:, None] - traj_timestamps[None, :]), axis=0)
    vals = np.clip(clamp_vals[idx].astype(np.float64), 0, clamp_max)
    # 夹爪数据 0~90 → 机械臂 255~0：robot = 255 * (clamp_max - val) / clamp_max
    robot_vals = np.round(255.0 * (clamp_max - vals) / clamp_max).astype(np.int32)
    return np.clip(robot_vals, 0, 255)


def load_trajectory(path):
    """加载轨迹文件，返回 (N, 8) 数组：timestamp, x, y, z, qx, qy, qz, qw"""
    data = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 8:
                row = [float(parts[i]) for i in range(8)]
                data.append(row)
    return np.array(data) if data else None


def quat_to_euler_deg(qx, qy, qz, qw):
    """四元数 (qx,qy,qz,qw) -> 欧拉角 (roll, pitch, yaw) 度"""
    r = R.from_quat([qx, qy, qz, qw])
    return r.as_euler('xyz', degrees=True)


def transform_to_base_quat(x, y, z, qx, qy, qz, qw, T_base_to_local):
    """
    将 local 坐标系下的位姿 (x,y,z, 四元数) 变换到 base 坐标系。
    与 rollout_Xarm_replay_tcp_xvsion.py 中逻辑一致。
    """
    rotation_local = R.from_quat([qx, qy, qz, qw]).as_matrix()
    T_local = np.eye(4)
    T_local[:3, :3] = rotation_local
    T_local[:3, 3] = [x, y, z]
    T_base_r = np.matmul(T_local[:3, :3], T_base_to_local[:3, :3])
    x_base, y_base, z_base = T_base_to_local[:3, 3] + T_local[:3, 3]
    rotation_base = R.from_matrix(T_base_r)
    roll_base, pitch_base, yaw_base = rotation_base.as_euler('xyz', degrees=True)
    qx_base, qy_base, qz_base, qw_base = rotation_base.as_quat()
    return x_base, y_base, z_base, qx_base, qy_base, qz_base, qw_base, roll_base, pitch_base, yaw_base


def build_T_base_to_local(base_x, base_y, base_z, base_roll_deg, base_pitch_deg, base_yaw_deg):
    """根据 base 原点及欧拉角 (度) 构建 T_base_to_local 4x4 矩阵。"""
    base_roll, base_pitch, base_yaw = np.deg2rad([base_roll_deg, base_pitch_deg, base_yaw_deg])
    rotation_base_to_local = R.from_euler('xyz', [base_roll, base_pitch, base_yaw]).as_matrix()
    T_base_to_local = np.eye(4)
    T_base_to_local[:3, :3] = rotation_base_to_local
    T_base_to_local[:3, 3] = [base_x, base_y, base_z]
    return T_base_to_local


def trajectory_to_poses(traj, T_base_to_local=None):
    """
    将轨迹数组 (N, 8) 转为 xarm 位姿列表。
    每行: timestamp, x_m, y_m, z_m, qx, qy, qz, qw（local 系，单位米，四元数 xyzw）
    若提供 T_base_to_local，先经 transform_to_base_quat 变换到 base 系再转毫米与欧拉角。
    返回: list of [x_mm, y_mm, z_mm, roll_deg, pitch_deg, yaw_deg]
    """
    poses = []
    for row in traj:
        t, x, y, z, qx, qy, qz, qw = row[:8]
        if T_base_to_local is not None:
            x_base, y_base, z_base, _, _, _, _, roll, pitch, yaw = transform_to_base_quat(
                x, y, z, qx, qy, qz, qw, T_base_to_local
            )
        else:
            roll, pitch, yaw = quat_to_euler_deg(qx, qy, qz, qw)
            x_base, y_base, z_base = x, y, z
        # 位姿为米，xarm set_position 为毫米
        x_mm = x_base * 1000.0
        y_mm = y_base * 1000.0
        z_mm = z_base * 1000.0
        poses.append([x_mm, y_mm, z_mm, roll, pitch, yaw])
    return poses


def main():
    parser = argparse.ArgumentParser(description='双臂轨迹复现')
    parser.add_argument('--robot0_ip', type=str, default='192.168.1.224', help='左臂 IP')
    parser.add_argument('--robot1_ip', type=str, default='192.168.1.235', help='右臂 IP')
    parser.add_argument('--replay_dir', type=str, default='/home/lumos/Data/K001/pass_packages/2026-01-30/task_20260125K001/background_01/multi_sessions_20260130_090942/session_001',
                        help='轨迹文件所在目录')
    parser.add_argument('--left_file', type=str, default='left_merged_trajectory.txt')
    parser.add_argument('--right_file', type=str, default='right_merged_trajectory.txt')
    parser.add_argument('--left_clamp_file', type=str, default='left_clamp_data_tum.txt',
                        help='左臂夹爪 TUM 文件，每行 timestamp value')
    parser.add_argument('--right_clamp_file', type=str, default='right_clamp_data_tum.txt',
                        help='右臂夹爪 TUM 文件')
    parser.add_argument('--dt', type=float, default=0.04, help='每步间隔(秒)，与 rollout 一致')
    parser.add_argument('--gripper', type=int, default=0,
                        help='无夹爪文件时使用的夹爪位置 0~255（机械臂控制值）')
    parser.add_argument('--clamp_max', type=float, default=90.0,
                        help='夹爪数据文件中的数值范围上限（0~clamp_max 会映射为机械臂 255~0）')
    parser.add_argument('--no_gripper', action='store_true', help='不发送夹爪指令')
    parser.add_argument('--dry_run', action='store_true', help='只打印位姿，不连机器人')
    # 与 rollout_Xarm_replay_tcp_xvsion.py 一致的 base 坐标变换（local -> base）
    parser.add_argument('--base_x', type=float, default=0.158, help='base 原点 x (米)')
    parser.add_argument('--base_y', type=float, default=0.28, help='base 原点 y (米)')
    parser.add_argument('--base_z', type=float, default=0.145, help='base 原点 z (米)')
    parser.add_argument('--base_roll', type=float, default=180.0, help='base 欧拉角 roll (度)')
    parser.add_argument('--base_pitch', type=float, default=-90.0, help='base 欧拉角 pitch (度)')
    parser.add_argument('--base_yaw', type=float, default=0.0, help='base 欧拉角 yaw (度)')
    parser.add_argument('--no_transform', action='store_true',
                        help='不做 local->base 变换，轨迹直接当作 base 系（旧行为）')
    args = parser.parse_args()

    import os
    left_path = os.path.join(args.replay_dir, args.left_file)
    right_path = os.path.join(args.replay_dir, args.right_file)
    left_clamp_path = os.path.join(args.replay_dir, args.left_clamp_file)
    right_clamp_path = os.path.join(args.replay_dir, args.right_clamp_file)
    if not os.path.isfile(left_path):
        raise FileNotFoundError(f'左臂轨迹文件不存在: {left_path}')
    if not os.path.isfile(right_path):
        raise FileNotFoundError(f'右臂轨迹文件不存在: {right_path}')

    left_traj = load_trajectory(left_path)
    right_traj = load_trajectory(right_path)
    if left_traj is None or len(left_traj) == 0:
        raise ValueError('左臂轨迹为空')
    if right_traj is None or len(right_traj) == 0:
        raise ValueError('右臂轨迹为空')

    # 与 rollout_Xarm_replay_tcp_xvsion.py 一致：构建 T_base_to_local，将轨迹从 local 变换到 base
    T_base_to_local = None
    if not args.no_transform:
        T_base_to_local = build_T_base_to_local(
            args.base_x, args.base_y, args.base_z,
            args.base_roll, args.base_pitch, args.base_yaw
        )
        print(f'使用 local->base 变换: base_xyz=({args.base_x},{args.base_y},{args.base_z}) m, '
              f'rpy=({args.base_roll},{args.base_pitch},{args.base_yaw}) deg')
    else:
        print('未使用坐标变换 (--no_transform)，轨迹直接当作 base 系')

    poses_left = trajectory_to_poses(left_traj, T_base_to_local)
    poses_right = trajectory_to_poses(right_traj, T_base_to_local)
    n_left, n_right = len(poses_left), len(poses_right)
    n_steps = min(n_left, n_right)
    print(f'左臂轨迹点数: {n_left}, 右臂轨迹点数: {n_right}, 复现步数: {n_steps}')

    # 夹爪：按时间戳对齐到轨迹步；无文件或对齐失败时用 --gripper
    gripper_left_arr = None
    gripper_right_arr = None
    if os.path.isfile(left_clamp_path):
        clamp_ts_l, clamp_vals_l = load_clamp_tum(left_clamp_path)
        gripper_left_arr = align_clamp_to_trajectory(
            left_traj[:, 0], clamp_ts_l, clamp_vals_l, clamp_max=args.clamp_max
        )
        if gripper_left_arr is not None:
            print(f'已加载左臂夹爪: {left_clamp_path}, 点数 {len(clamp_ts_l)} (0~{args.clamp_max}→255~0)')
    if os.path.isfile(right_clamp_path):
        clamp_ts_r, clamp_vals_r = load_clamp_tum(right_clamp_path)
        gripper_right_arr = align_clamp_to_trajectory(
            right_traj[:, 0], clamp_ts_r, clamp_vals_r, clamp_max=args.clamp_max
        )
        if gripper_right_arr is not None:
            print(f'已加载右臂夹爪: {right_clamp_path}, 点数 {len(clamp_ts_r)} (0~{args.clamp_max}→255~0)')
    default_gripper = int(np.clip(args.gripper, 0, 255))

    # if args.dry_run:
    #     for i in range(min(5, n_steps)):
    #         print(f'Step {i} Left: {poses_left[i]}, Right: {poses_right[i]}')
    #     print('... (dry_run 仅打印前 5 步)')
    #     return

    # 连接双臂（与 rollout 一致）
    arm_left = XArmAPI(args.robot0_ip)
    time.sleep(0.5)
    arm_left.set_mode(0)
    # arm_left.set_mode(1)
    arm_left.set_state(0)
    arm_left.motion_enable(enable=True)

    arm_right = XArmAPI(args.robot1_ip)
    time.sleep(0.5)
    arm_right.set_mode(0)
    # arm_left.set_mode(1)
    arm_right.set_state(0)
    arm_right.motion_enable(enable=True)

    # 初始位姿（与 rollout 一致）
    arm_left.set_position(*[158, 280, 145, 180, -90, 0], speed=10000, mvacc=500000,  wait=False)
    arm_right.set_position(*[158, 280, 145, 180, -90, 0], speed=10000, mvacc=500000,  wait=False)
    # arm_left.set_servo_cartesian([158, 280, 145, 180, -90, 0], wait=False)
    # arm_right.set_servo_cartesian([158, 280, 145, 180, -90, 0], wait=False)
    arm_left.robotiq_set_position(0)
    arm_right.robotiq_set_position(0)
    time.sleep(0.3)
    print('双臂初始化完成，开始复现轨迹...')

    for i in tqdm(range(n_steps), desc='复现轨迹', unit='步'):
        pl = poses_left[i]
        pr = poses_right[i]
        # 与 rollout 一致：set_position(x, y, z, roll, pitch, yaw, wait=False)
        arm_left.set_position(pl[0], pl[1], pl[2], pl[3], pl[4], pl[5], speed=1000000, mvacc=500000,  wait=False)
        arm_right.set_position(pr[0], pr[1], pr[2], pr[3], pr[4], pr[5], speed=100000, mvacc=500000,  wait=False)
        # arm_left.set_servo_cartesian([pl[0], pl[1], pl[2], pl[3], pl[4], pl[5]], wait=False)
        # arm_right.set_servo_cartesian([pr[0], pr[1], pr[2], pr[3], pr[4], pr[5]], wait=False)
        if not args.no_gripper:
            gl = int(gripper_left_arr[i]) if gripper_left_arr is not None else default_gripper
            gr = int(gripper_right_arr[i]) if gripper_right_arr is not None else default_gripper
            arm_left.robotiq_set_position(gl, wait=False)
            arm_right.robotiq_set_position(gr, wait=False)
        time.sleep(0.1)

    print('轨迹复现结束。')


if __name__ == '__main__':
    main()
