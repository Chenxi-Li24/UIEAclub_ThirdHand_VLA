"""
SEUCM (Stereographic projection-based Enhanced Unified Camera Model)
适用于 Lumos Ego 1280×1280 超广角 RGB 相机

SEUCM 投影公式:
  给定 3D 点 P = (X, Y, Z) 在相机坐标系中:
    d = sqrt(beta * (X² + Y²) + Z²)
    s = alpha * d + (1 - alpha) * Z
    u = fx * X / s + u0
    v = fy * Y / s + v0

SEUCM 反投影公式 (像素 → 单位球面上的射线):
  给定像素 (u, v):
    xn = (u - u0) / fx
    yn = (v - v0) / fy
    r2 = xn² + yn²
    Z = (1 - alpha² * beta * r2) / (alpha * sqrt(1 - (alpha² - beta) * r2) + 1 - alpha)
    当 alpha² - beta > 0 且 r2 > 1/(alpha² - beta) 时，该像素超出有效投影范围
    X = xn, Y = yn (归一化后指向单位球面)
"""

import numpy as np
from camera_params import RGB_SEUCM


class SEUCMModel:
    """SEUCM 相机模型"""

    def __init__(self, params=None):
        p = params or RGB_SEUCM
        self.fx = p["fx"]
        self.fy = p["fy"]
        self.u0 = p["u0"]
        self.v0 = p["v0"]
        self.alpha = p["alpha"]
        self.beta = p["beta"]
        self.w = p["w"]
        self.h = p["h"]

        # 预计算
        self.K = np.array([
            [self.fx, 0, self.u0],
            [0, self.fy, self.v0],
            [0, 0, 1]
        ], dtype=np.float64)

        self.a2 = self.alpha ** 2
        self.a2b = self.a2 - self.beta  # alpha² - beta
        self.a2beta = self.a2 * self.beta

    def project(self, points_3d):
        """
        将 3D 点投影到像素坐标
        points_3d: (N, 3) 相机坐标系下的 3D 点
        返回: (N, 2) 像素坐标 (u, v), (N,) 有效掩码
        """
        X = points_3d[:, 0]
        Y = points_3d[:, 1]
        Z = points_3d[:, 2]

        # 只投影 Z > 0 的点
        valid = Z > 0

        r2_xy = X**2 + Y**2
        d = np.sqrt(self.beta * r2_xy + Z**2)
        s = self.alpha * d + (1 - self.alpha) * Z

        # 防止除零
        s = np.where(s > 1e-10, s, 1e-10)

        u = self.fx * X / s + self.u0
        v = self.fy * Y / s + self.v0

        # 检查图像边界
        in_bounds = (u >= 0) & (u < self.w) & (v >= 0) & (v < self.h)
        valid = valid & in_bounds

        return np.stack([u, v], axis=-1), valid

    def unproject(self, pixels):
        """
        将像素坐标反投影到单位球面上的 3D 射线方向
        pixels: (N, 2) 像素坐标 (u, v)
        返回: (N, 3) 单位球面上的方向向量 (归一化后)
        """
        xn = (pixels[:, 0] - self.u0) / self.fx
        yn = (pixels[:, 1] - self.v0) / self.fy
        r2 = xn**2 + yn**2

        # SEUCM 反投影公式
        # 检查有效范围
        if self.a2b > 0:
            max_r2 = 1.0 / self.a2b
            valid = r2 < max_r2
        else:
            valid = np.ones_like(r2, dtype=bool)

        sqrt_term = np.sqrt(np.maximum(1 - self.a2b * r2, 0))
        denom = self.alpha * sqrt_term + (1 - self.alpha)
        denom = np.where(denom > 1e-10, denom, 1e-10)

        Z = (1 - self.a2beta * r2) / denom

        # 归一化到单位球面
        norm = np.sqrt(xn**2 + yn**2 + Z**2)
        norm = np.where(norm > 1e-10, norm, 1e-10)

        X_dir = xn / norm
        Y_dir = yn / norm
        Z_dir = Z / norm

        return np.stack([X_dir, Y_dir, Z_dir], axis=-1), valid

    def project_with_depth(self, points_3d, depth_scale=1.0):
        """
        投影 3D 点，同时返回深度值
        points_3d: (N, 3) 相机坐标系下的 3D 点
        返回: (N, 2) 像素坐标, (N,) 深度值, (N,) 有效掩码
        """
        pixels, valid = self.project(points_3d)
        depth = np.linalg.norm(points_3d, axis=1)
        return pixels, depth, valid

    def get_fov(self):
        """估算水平/垂直视场角 (度)"""
        # 通过投影四个角点来计算
        corners_3d = []
        for u in [0, self.w]:
            for v in [0, self.h]:
                ray, _ = self.unproject(np.array([[u, v]]))
                corners_3d.append(ray[0])
        corners_3d = np.array(corners_3d)

        # 计算角度
        angles_h = []
        angles_v = []
        for pt in corners_3d:
            # 水平角
            h_angle = np.arctan2(pt[0], pt[2])
            v_angle = np.arctan2(pt[1], pt[2])
            angles_h.append(h_angle)
            angles_v.append(v_angle)

        hfov = (np.max(angles_h) - np.min(angles_h)) * 180 / np.pi
        vfov = (np.max(angles_v) - np.min(angles_v)) * 180 / np.pi
        return hfov, vfov

    def undistort_to_pinhole(self, pixels, pinhole_fx=None, pinhole_fy=None,
                             output_w=None, output_h=None):
        """
        将 SEUCM 图像去畸变到针孔模型
        使用反投影 + 虚拟针孔重投影
        """
        if pinhole_fx is None:
            pinhole_fx = self.fx
        if pinhole_fy is None:
            pinhole_fy = self.fy
        if output_w is None:
            output_w = self.w
        if output_h is None:
            output_h = self.h

        # 对每个像素反投影得到 3D 射线
        rays, valid = self.unproject(pixels)

        # 用虚拟针孔相机重新投影
        u_new = pinhole_fx * rays[:, 0] / rays[:, 2] + output_w / 2
        v_new = pinhole_fy * rays[:, 1] / rays[:, 2] + output_h / 2

        return np.stack([u_new, v_new], axis=-1), valid


def create_seucm_camera_matrix():
    """返回 OpenCV 兼容的内参矩阵 (仅作近似参考)"""
    p = RGB_SEUCM
    return np.array([
        [p["fx"], 0, p["u0"]],
        [0, p["fy"], p["v0"]],
        [0, 0, 1]
    ], dtype=np.float64)


if __name__ == "__main__":
    model = SEUCMModel()

    # 测试: 打印 FOV
    hfov, vfov = model.get_fov()
    print(f"估算视场角: HFOV={hfov:.1f}°, VFOV={vfov:.1f}°")

    # 测试: 图像中心点的反投影方向
    center_ray, _ = model.unproject(np.array([[model.u0, model.v0]]))
    print(f"图像中心的反投影方向: {center_ray[0]} (应接近 Z 轴 [0, 0, 1])")

    # 测试: 正前方 1m 远的点的投影
    pt_1m = np.array([[0.0, 0.0, 1.0]])
    pixel, valid = model.project(pt_1m)
    print(f"正前方 1m 点的投影像素: {pixel[0] if valid[0] else '超出范围'}")
