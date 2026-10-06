from datetime import datetime
from pathlib import Path
import re

import numpy as np
from scipy.spatial.transform import Rotation as R


def parse_timestamp_from_name(name: str):
    match = re.search(r"multi_sessions?_(\d{8})_(\d{6})", name)
    if match:
        date_str, time_str = match.groups()
        try:
            return datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return None


def select_multi_sessions_dir(base_path):
    base = Path(base_path).expanduser()

    def sort_key(p):
        dt = parse_timestamp_from_name(p.name)
        return (dt or datetime.min, p.name)

    def get_sorted_dirs():
        dirs = [p for p in base.glob("multi_session*") if p.is_dir()]
        return sorted(dirs, key=sort_key, reverse=True)

    def print_multi_dirs(sorted_dirs):
        print("\n📁 可用的多会话记录（最新在前）：")
        print("─" * 50)
        for i, d in enumerate(sorted_dirs, 1):
            dt = parse_timestamp_from_name(d.name)
            time_label = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "???"
            print(f"[{i:2}] {time_label}  →  {d.name}")
        print("─" * 50)

    sorted_dirs = get_sorted_dirs()
    if not sorted_dirs:
        raise FileNotFoundError(f"未找到任何 'multi_session*' 目录: {base}")
    print_multi_dirs(sorted_dirs)

    while True:
        try:
            choice = input("\n➤ 请输入多会话编号（直接回车=最新，输入r=刷新列表）：").strip()
            if choice == "r":
                sorted_dirs = get_sorted_dirs()
                if not sorted_dirs:
                    print("当前目录下未找到可用的 multi_session* 目录。")
                    continue
                print_multi_dirs(sorted_dirs)
                continue
            if not choice:
                selected_root = sorted_dirs[0]
                print(f"→ 使用最新会话根目录：{selected_root.name}")
                return selected_root
            idx = int(choice)
            if 1 <= idx <= len(sorted_dirs):
                selected_root = sorted_dirs[idx - 1]
                print(f"→ 已选择：{selected_root.name}")
                return selected_root
            print(f"⚠️  编号无效，请输入 1–{len(sorted_dirs)} 之间的数字。")
        except ValueError:
            print("⚠️  请输入有效数字，或直接回车选择最新会话。")


def select_session_subdir(multi_session_root: Path):
    def get_session_dirs():
        return sorted(
            [p for p in Path(multi_session_root).glob("session_*") if p.is_dir()],
            key=lambda p: p.name,
        )

    def print_session_dirs(session_dirs):
        print(f"\n📂 当前多会话：{Path(multi_session_root).name}")
        print("📁 可用的子会话（按编号升序排列）：")
        print("─" * 45)
        for i, d in enumerate(session_dirs, 1):
            print(f"[{i:2}] {d.name}")
        print("─" * 45)

    session_dirs = get_session_dirs()
    if not session_dirs:
        raise FileNotFoundError(f"在 '{multi_session_root}' 下未找到任何 'session_*' 子目录。")
    print_session_dirs(session_dirs)

    while True:
        try:
            choice = input("\n➤ 请输入子会话编号（直接回车=最新，输入r=刷新列表）：").strip()
            if choice == "r":
                session_dirs = get_session_dirs()
                if not session_dirs:
                    print(f"⚠️  在 '{Path(multi_session_root).name}' 下未找到可用子会话。")
                    continue
                print_session_dirs(session_dirs)
                continue
            if not choice:
                selected = session_dirs[-1]
                print(f"→ 使用最新子会话：{selected.name}")
                return selected
            idx = int(choice)
            if 1 <= idx <= len(session_dirs):
                selected = session_dirs[idx - 1]
                print(f"→ 已选择子会话：{selected.name}")
                return selected
            print(f"⚠️  编号无效，请输入 1–{len(session_dirs)} 之间的数字。")
        except ValueError:
            print("⚠️  请输入有效数字，或直接回车选择最新会话。")


def load_trajectory(traj_path: str, clamp_path: str):
    try:
        raw_clamp = np.loadtxt(clamp_path)
        raw_pose = np.loadtxt(traj_path)
        pose_timestamps = raw_pose[:, 0]
        raw_pose = raw_pose[:, 1:]
    except Exception as e:
        raise FileNotFoundError(f"加载轨迹数据失败: {e}") from e

    return raw_pose, raw_clamp, pose_timestamps


def transform_to_base_quat(x, y, z, qx, qy, qz, qw, T_base_to_local, degrees=False):
    T_base_to_local = np.asarray(T_base_to_local, dtype=float)
    rotation_local = R.from_quat([qx, qy, qz, qw]).as_matrix()
    T_local = np.eye(4)
    T_local[:3, :3] = rotation_local
    T_local[:3, 3] = [x, y, z]

    T_base = T_base_to_local @ T_local
    x_base, y_base, z_base = T_base[:3, 3]
    roll_base, pitch_base, yaw_base = R.from_matrix(T_base[:3, :3]).as_euler("xyz", degrees=degrees)
    return x_base, y_base, z_base, roll_base, pitch_base, yaw_base


def transform_traj(raw_pose, raw_clamp, pose_timestamps, T_base2local):
    target_pose = []
    target_clamp_width = []

    clamp_timestamps = raw_clamp[:, 0]
    umi_clamp_widths = raw_clamp[:, -1]

    for p, pose_ts in zip(raw_pose, pose_timestamps):
        idx = np.abs(clamp_timestamps - pose_ts).argmin()
        real_width = np.clip(umi_clamp_widths[idx], 0, 85)
        target_clamp_width.append(real_width)
        target_pose.append(transform_to_base_quat(*p, T_base2local))
    return target_pose, target_clamp_width
