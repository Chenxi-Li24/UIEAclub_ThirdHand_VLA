import numpy as np


def parse_tool_offset_xyz(text):
    values = [float(part.strip()) for part in str(text).split(",") if part.strip()]
    if len(values) != 3:
        raise ValueError(f"tcp offset must contain 3 comma-separated values, got: {text!r}")
    return np.asarray(values, dtype=np.float64)


def _rotation_matrix_from_euler_xyz(euler_rad):
    roll, pitch, yaw = [float(v) for v in euler_rad]
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    return np.asarray(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ],
        dtype=np.float64,
    )


def _rotation_matrix_from_quaternion_wxyz(quat_wxyz):
    w, x, y, z = [float(v) for v in quat_wxyz]
    norm = np.sqrt(w * w + x * x + y * y + z * z)
    if norm <= 0.0:
        raise ValueError("quaternion norm must be positive")
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return np.asarray(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def flange_position_to_tcp(flange_pos, quat_wxyz, tcp_offset_xyz):
    flange_pos = np.asarray(flange_pos, dtype=np.float64)
    tcp_offset_xyz = np.asarray(tcp_offset_xyz, dtype=np.float64)
    if flange_pos.shape != (3,) or tcp_offset_xyz.shape != (3,):
        raise ValueError("flange_pos and tcp_offset_xyz must both be length 3")
    return flange_pos + _rotation_matrix_from_quaternion_wxyz(quat_wxyz) @ tcp_offset_xyz


def tcp_position_to_flange(tcp_pos, euler_rad, tcp_offset_xyz):
    tcp_pos = np.asarray(tcp_pos, dtype=np.float64)
    tcp_offset_xyz = np.asarray(tcp_offset_xyz, dtype=np.float64)
    if tcp_pos.shape != (3,) or tcp_offset_xyz.shape != (3,):
        raise ValueError("tcp_pos and tcp_offset_xyz must both be length 3")
    return tcp_pos - _rotation_matrix_from_euler_xyz(euler_rad) @ tcp_offset_xyz
