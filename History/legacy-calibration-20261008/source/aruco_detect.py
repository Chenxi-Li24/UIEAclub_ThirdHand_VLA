"""
ArUco / ChArUco Marker 检测与位姿估计
支持:
  - ArUco marker 检测、ID 读取、角点定位
  - SEUCM 模型下的位姿估计 (solvePnP with omnidirectional model)
  - ChArUco 板检测 (用于相机标定)
  - 桌面单应性映射 (基础版坐标转换)
"""

import numpy as np
import cv2
from camera_params import RGB_SEUCM


class ArUcoDetector:
    """ArUco Marker 检测器"""

    def __init__(self, dictionary=cv2.aruco.DICT_4X4_50, seucm_params=None):
        """
        dictionary: ArUco 字典类型
        seucm_params: SEUCM 相机参数字典
        """
        self.params = seucm_params or RGB_SEUCM
        self.dict = cv2.aruco.getPredefinedDictionary(dictionary)
        self.detector_params = cv2.aruco.DetectorParameters()

        # 相机内参矩阵 (OpenCV 针孔近似，用于 solvePnP)
        self.K = np.array([
            [self.params["fx"], 0, self.params["u0"]],
            [0, self.params["fy"], self.params["v0"]],
            [0, 0, 1]
        ], dtype=np.float64)

        # 畸变系数 (使用 OpenCV omnidir 模型近似 SEUCM)
        # xi = alpha / (1 - alpha), 适用于 omnidir 模型
        alpha = self.params["alpha"]
        self.xi = alpha / (1 - alpha) if alpha < 1 else 10.0
        self.dist_coeffs = np.zeros(4)  # omnidir 不需要传统畸变系数

        self.last_corners = None
        self.last_ids = None

    def detect(self, image):
        """
        检测图像中的 ArUco markers
        image: BGR 图像
        返回: (corners, ids, rejected)
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        corners, ids, rejected = cv2.aruco.detectMarkers(
            gray, self.dict, parameters=self.detector_params
        )
        self.last_corners = corners
        self.last_ids = ids
        return corners, ids, rejected

    def draw_markers(self, image, corners=None, ids=None):
        """在图像上绘制检测到的 markers"""
        if corners is None:
            corners = self.last_corners
        if ids is None:
            ids = self.last_ids
        if corners is None or ids is None:
            return image
        return cv2.aruco.drawDetectedMarkers(image.copy(), corners, ids)

    def estimate_pose_single_marker(self, corners, marker_size_m=0.05):
        """
        估计单个 marker 的位姿
        marker_size_m: marker 边长 (米)

        返回: (rvec, tvec, success)
          rvec: 旋转向量 (Rodrigues), 相机→marker
          tvec: 平移向量 (米), 相机→marker
        使用 solvePnP + 针孔近似 (对超广角相机，小范围有效)
        """
        # Marker 的 3D 角点 (在 marker 坐标系中，以 marker 中心为原点)
        half = marker_size_m / 2
        obj_points = np.array([
            [-half, -half, 0],
            [ half, -half, 0],
            [ half,  half, 0],
            [-half,  half, 0],
        ], dtype=np.float64)

        corners = corners.reshape(4, 2).astype(np.float64)

        # 使用 solvePnP (针孔模型近似)
        success, rvec, tvec = cv2.solvePnP(
            obj_points, corners, self.K, None,
            flags=cv2.SOLVEPNP_IPPE_SQUARE
        )

        return rvec, tvec, success

    def estimate_pose_omnidir(self, corners, marker_size_m=0.05):
        """
        使用 omnidirectional 模型估计 marker 位姿
        更适合超广角相机
        """
        half = marker_size_m / 2
        obj_points = np.array([
            [-half, -half, 0],
            [ half, -half, 0],
            [ half,  half, 0],
            [-half,  half, 0],
        ], dtype=np.float64)

        corners_flat = corners.reshape(4, 1, 2).astype(np.float64)
        obj_points_flat = obj_points.reshape(4, 1, 3).astype(np.float64)

        # OpenCV omnidirectional 模型 solvePnP
        success, rvec, tvec = cv2.solvePnP(
            obj_points_flat, corners_flat,
            self.K, self.dist_coeffs,
            flags=cv2.SOLVEPNP_IPPE_SQUARE
        )

        return rvec, tvec, success

    def draw_pose_axes(self, image, rvec, tvec, length=0.03):
        """在图像上绘制位姿坐标轴"""
        return cv2.drawFrameAxes(image.copy(), self.K, None,
                                 rvec, tvec, length)

    def get_marker_centers(self, corners):
        """获取每个 marker 的中心像素坐标"""
        centers = []
        for c in corners:
            c = c.reshape(4, 2)
            center = c.mean(axis=0)
            centers.append(center)
        return np.array(centers)


class CharucoBoardDetector:
    """ChArUco 板检测器 — 用于相机标定"""

    def __init__(self, squares_x=5, squares_y=7,
                 square_length=0.04, marker_length=0.02,
                 dictionary=cv2.aruco.DICT_4X4_50):
        """
        squares_x, squares_y: 棋盘格的行列数
        square_length: 方格边长 (米)
        marker_length: ArUco marker 边长 (米)
        """
        self.board = cv2.aruco.CharucoBoard(
            (squares_x, squares_y),
            square_length, marker_length,
            cv2.aruco.getPredefinedDictionary(dictionary)
        )
        self.detector_params = cv2.aruco.DetectorParameters()
        self.dict = cv2.aruco.getPredefinedDictionary(dictionary)

    def detect(self, image):
        """
        检测 ChArUco 板的角点
        返回: (charuco_corners, charuco_ids, marker_corners, marker_ids)
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        marker_corners, marker_ids, _ = cv2.aruco.detectMarkers(
            gray, self.dict, parameters=self.detector_params
        )

        if marker_ids is None or len(marker_ids) < 4:
            return None, None, marker_corners, marker_ids

        ret, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(
            marker_corners, marker_ids, gray, self.board
        )
        return charuco_corners, charuco_ids, marker_corners, marker_ids

    def draw_results(self, image, charuco_corners, charuco_ids):
        """绘制 ChArUco 检测结果"""
        return cv2.aruco.drawDetectedCornersCharuco(
            image.copy(), charuco_corners, charuco_ids
        )

    def get_object_points(self):
        """获取 ChArUco 板的 3D 点"""
        return self.board.getObjPoints(), self.board.getIds()


class DesktopPlaneMapper:
    """
    桌面平面映射器 (基础版坐标转换)
    原理: 检测桌面上的 ArUco marker → 计算单应性 H →
          像素中心 → base 坐标系 XY (假设桌面 Z 已知)
    """

    def __init__(self, desktop_z=0.0):
        """
        desktop_z: 桌面在 base 坐标系中的 Z 高度 (米)
        """
        self.desktop_z = desktop_z
        self.H = None  # 像素 → base XY 的单应性矩阵

    def calibrate_from_marker(self, pixel_point, base_xy):
        """
        用一个已知 marker 位置来计算平移偏移
        pixel_point: marker 在图像中的中心像素 (u, v)
        base_xy: marker 在 base 坐标系中的 (X, Y) 位置 (米)

        这是最简单的标定: 假设桌面与相机成像平面平行
        """
        self.pixel_ref = np.array(pixel_point)
        self.base_ref = np.array(base_xy)

    def pixel_to_base_xy(self, pixel, scale_x, scale_y):
        """
        将像素转换为 base 坐标系的 XY
        pixel: (u, v)
        scale_x, scale_y: 每像素对应的世界尺度 (米/像素), 需要在已知距离标定
        """
        dp = np.array(pixel) - self.pixel_ref
        base_x = self.base_ref[0] + dp[0] * scale_x
        base_y = self.base_ref[1] + dp[1] * scale_y
        return np.array([base_x, base_y])

    def calibrate_homography(self, pixel_points, base_xy_points):
        """
        用多个对应点计算像素 → base XY 的单应性矩阵
        pixel_points: (N, 2) 像素坐标
        base_xy_points: (N, 2) base 坐标系 XY 坐标
        """
        self.H, _ = cv2.findHomography(
            pixel_points.astype(np.float64),
            base_xy_points.astype(np.float64),
            method=cv2.RANSAC
        )
        return self.H

    def pixel_to_base_homography(self, pixel):
        """用单应性矩阵转换像素到 base XY"""
        if self.H is None:
            raise ValueError("请先调用 calibrate_homography 标定单应性矩阵")
        p = np.array([pixel[0], pixel[1], 1.0])
        base_xy = self.H @ p
        base_xy = base_xy[:2] / base_xy[2]
        return base_xy


# ============================================================
# 实时检测演示
# ============================================================
def demo_realtime(camera_id=0):
    """实时 ArUco 检测演示"""
    from seucm_model import SEUCMModel

    cap = cv2.VideoCapture(camera_id)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)

    detector = ArUcoDetector()
    seucm = SEUCMModel()

    print("按 'q' 退出, 's' 保存当前帧")
    print(f"相机 FOV: {seucm.get_fov()}")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("无法读取图像")
            break

        corners, ids, _ = detector.detect(frame)

        if corners and ids:
            frame = detector.draw_markers(frame, corners, ids)

            # 估计第一个 marker 的位姿
            rvec, tvec, success = detector.estimate_pose_single_marker(
                corners[0], marker_size_m=0.05
            )
            if success:
                frame = detector.draw_pose_axes(frame, rvec, tvec)
                print(f"\rID={ids[0][0]}, t=[{tvec[0][0]:.3f}, {tvec[1][0]:.3f}, {tvec[2][0]:.3f}]m", end="")

        cv2.imshow("ArUco Detection", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            cv2.imwrite("aruco_snapshot.png", frame)
            print("\n已保存截图")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo_realtime()
    else:
        print("用法: python aruco_detect.py demo  # 实时检测演示")
        print("      python aruco_detect.py       # 导入为模块使用")
