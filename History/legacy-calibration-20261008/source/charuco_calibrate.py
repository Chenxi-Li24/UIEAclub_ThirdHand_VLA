"""
ChArUco 标定工具 — 相机标定 + 桌面映射
用法:
  python charuco_calibrate.py calib    # 采集图像，标定相机内参
  python charuco_calibrate.py desktop  # 桌面平面标定 (像素→世界坐标)
  python charuco_calibrate.py live     # 实时检测预览
"""

import sys
import os
import time
import json
import numpy as np
import cv2

# ============================================================
# ChArUco 板参数 — 根据你的实际板子修改这里！
# ============================================================
SQUARES_X = 9           # 棋盘格列数
SQUARES_Y = 12          # 棋盘格行数
SQUARE_LENGTH = 0.015   # 方格边长 15mm
MARKER_LENGTH = 0.01125 # ArUco 标记边长 11.25mm
DICTIONARY = cv2.aruco.DICT_4X4_50

# 标定图像保存目录
CALIB_DIR = "charuco_images"
OUTPUT_FILE = "camera_calib.json"


# ============================================================
# ChArUco 检测器
# ============================================================
class CharucoDetector:
    def __init__(self):
        self.dict = cv2.aruco.getPredefinedDictionary(DICTIONARY)
        self.board = cv2.aruco.CharucoBoard(
            (SQUARES_X, SQUARES_Y),
            SQUARE_LENGTH, MARKER_LENGTH,
            self.dict
        )
        self.params = cv2.aruco.DetectorParameters()

        # OpenCV 5.x compat
        if hasattr(cv2.aruco, 'ArucoDetector'):
            self._detector = cv2.aruco.ArucoDetector(self.dict, self.params)
            self._use_new_api = True
        else:
            self._detector = None
            self._use_new_api = False

    def detect(self, image):
        """检测 ChArUco 角点. 返回 (charuco_corners, charuco_ids, marker_corners, marker_ids)"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        if self._use_new_api:
            marker_corners, marker_ids, _ = self._detector.detectMarkers(gray)
        else:
            marker_corners, marker_ids, _ = cv2.aruco.detectMarkers(
                gray, self.dict, parameters=self.params
            )

        if marker_ids is None or len(marker_ids) < 4:
            return None, None, marker_corners, marker_ids

        n_corners, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(
            marker_corners, marker_ids, gray, self.board
        )
        return charuco_corners, charuco_ids, marker_corners, marker_ids

    def draw(self, image, charuco_corners, charuco_ids, marker_corners=None, marker_ids=None):
        out = image.copy()
        if marker_corners and marker_ids is not None and len(marker_corners) > 0:
            cv2.aruco.drawDetectedMarkers(out, marker_corners, marker_ids)
        if charuco_corners is not None and charuco_ids is not None:
            cv2.aruco.drawDetectedCornersCharuco(out, charuco_corners, charuco_ids)
        return out

    def get_board_points(self):
        """获取 ChArUco 板的 3D 对象点"""
        return self.board.getObjPoints(), self.board.getIds()


# ============================================================
# 相机采集
# ============================================================
class CameraCapture:
    def __init__(self):
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YU12'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        print(f"Camera: {int(self.cap.get(3))}x{int(self.cap.get(4))} @ {self.cap.get(5)}fps")

    def read(self):
        ret, frame = self.cap.read()
        if not ret:
            return None
        return cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)

    def release(self):
        self.cap.release()


# ============================================================
# 模式1: 采集图像 + 标定相机内参
# ============================================================
def mode_calib():
    print("=" * 50)
    print("ChArUco 相机标定 — 图像采集")
    print(f"板参数: {SQUARES_X}x{SQUARES_Y}, 方格{SQUARE_LENGTH*1000:.0f}mm, 标记{MARKER_LENGTH*1000:.0f}mm")
    print("=" * 50)
    print()
    print("操作:")
    print("  从不同角度拍摄 ChArUco 板")
    print("  按 's' 保存当前帧")
    print("  按 'c' 开始标定计算")
    print("  按 'q' 退出")
    print()

    os.makedirs(CALIB_DIR, exist_ok=True)

    cam = CameraCapture()
    detector = CharucoDetector()

    all_corners = []   # 每张图的角点 (像素)
    all_ids = []       # 每张图的角点 ID
    saved = 0

    while True:
        frame = cam.read()
        if frame is None:
            continue

        charuco_corners, charuco_ids, marker_corners, marker_ids = detector.detect(frame)
        display = detector.draw(frame, charuco_corners, charuco_ids,
                                marker_corners, marker_ids if marker_ids is not None else None)

        # 状态显示
        if charuco_corners is not None and charuco_ids is not None:
            n = len(charuco_corners)
            status = f"ChArUco: {n} corners | Saved: {saved}"
            color = (0, 255, 0)
        elif marker_ids is not None:
            status = f"Markers: {len(marker_ids)} (need 4+ for ChArUco) | Saved: {saved}"
            color = (0, 200, 255)
        else:
            status = f"No board detected | Saved: {saved}"
            color = (100, 100, 255)

        cv2.putText(display, status, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        cv2.putText(display, "[s]save [c]calibrate [q]quit", (20, 1240),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)

        cv2.imshow("Charuco Calibration", cv2.resize(display, (640, 640)))
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('s') and charuco_corners is not None and charuco_ids is not None:
            all_corners.append(charuco_corners)
            all_ids.append(charuco_ids)
            path = os.path.join(CALIB_DIR, f"charuco_{saved:04d}.png")
            cv2.imwrite(path, frame)
            saved += 1
            print(f"  [{saved}] Saved {path} ({len(charuco_corners)} corners)")
        elif key == ord('c') and saved >= 5:
            print(f"\n开始标定 (使用 {saved} 张图像)...")
            break
        elif key == ord('c'):
            print(f"\n至少需要 5 张图像，当前只有 {saved} 张")

    cam.release()
    cv2.destroyAllWindows()

    if saved < 5:
        print(f"图像不足 ({saved} < 5)，退出")
        return

    # ---- 标定计算 ----
    print(f"\n{'='*50}")
    print(f"计算相机标定 ({saved} 张图像)...")

    board_obj_points, board_ids = detector.get_board_points()

    obj_points = []  # 每张图的 3D 点
    img_points = []  # 每张图的 2D 点

    for corners, ids in zip(all_corners, all_ids):
        # 筛选出在 board 中定义的角点
        obj_pts = []
        img_pts = []
        for i, cid in enumerate(ids.flatten()):
            if cid in board_ids.flatten():
                idx = np.where(board_ids.flatten() == cid)[0][0]
                obj_pts.append(board_obj_points[idx].flatten())
                img_pts.append(corners[i].flatten())
        if len(obj_pts) >= 4:
            obj_points.append(np.array(obj_pts, dtype=np.float32))
            img_points.append(np.array(img_pts, dtype=np.float32))

    print(f"  有效图像: {len(obj_points)}/{saved}")

    # 先用标准针孔标定获取初值
    h, w = 1280, 1280
    ret, K, dist, rvecs, tvecs = cv2.calibrateCamera(
        obj_points, img_points, (w, h),
        None, None,
        flags=cv2.CALIB_RATIONAL_MODEL
    )
    print(f"  针孔标定 RMS: {ret:.4f}")
    print(f"  K = [{K[0,0]:.2f}, 0, {K[0,2]:.2f}; 0, {K[1,1]:.2f}, {K[1,2]:.2f}; 0, 0, 1]")

    # 用 fisheye 模型重新标定 (适合超广角)
    print(f"\n  Fisheye 标定...")
    obj_points_f = [p.reshape(-1, 1, 3) for p in obj_points]
    img_points_f = [p.reshape(-1, 1, 2) for p in img_points]

    K_f = K.copy()
    D_f = np.zeros(4)

    try:
        ret_f, K_f, D_f, rvecs_f, tvecs_f = cv2.fisheye.calibrate(
            obj_points_f, img_points_f, (w, h),
            K_f, D_f,
            flags=cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC |
                  cv2.fisheye.CALIB_FIX_SKEW,
            criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-6)
        )
        print(f"  Fisheye RMS: {ret_f:.4f}")
        print(f"  K = [{K_f[0,0]:.2f}, 0, {K_f[0,2]:.2f}; 0, {K_f[1,1]:.2f}, {K_f[1,2]:.2f}; 0, 0, 1]")
        print(f"  D = [{D_f[0]:.6f}, {D_f[1]:.6f}, {D_f[2]:.6f}, {D_f[3]:.6f}]")
    except Exception as e:
        print(f"  Fisheye failed: {e}, using pinhole")
        K_f = K
        D_f = dist.flatten()[:4]

    # 保存
    calib_data = {
        "model": "fisheye",
        "width": w, "height": h,
        "K": K_f.tolist(),
        "D": D_f.tolist(),
        "rms": float(ret_f) if 'ret_f' in dir() else float(ret),
        "num_images": saved,
        "device_seucm": {
            "fx": 392.168, "fy": 392.168,
            "u0": 637.761, "v0": 640.597,
            "alpha": 0.678979, "beta": 0.749026,
        }
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(calib_data, f, indent=2)
    print(f"\n  标定结果已保存: {OUTPUT_FILE}")

    # 对比设备内参
    print(f"\n  对比设备 SEUCM 内参:")
    print(f"    设备: fx=392.17  u0=637.76  v0=640.60")
    print(f"    标定: fx={K_f[0,0]:.2f}  u0={K_f[0,2]:.2f}  v0={K_f[1,2]:.2f}")


# ============================================================
# 模式2: 桌面平面标定
# ============================================================
def mode_desktop():
    print("=" * 50)
    print("桌面平面标定 — 像素 → 世界坐标映射")
    print("=" * 50)
    print()
    print("步骤:")
    print("  1. 把 ChArUco 板平放在桌面上")
    print("  2. 记录板的原点在机械臂基座坐标系中的位置")
    print("  3. 按 's' 拍摄并标定")
    print()

    cam = CameraCapture()
    detector = CharucoDetector()

    # 桌面标定参数
    print("请输入 ChArUco 板原点在机械臂基座中的坐标:")
    try:
        origin_x = float(input("  X (米): ") or "0.15")
        origin_y = float(input("  Y (米): ") or "0.0")
        origin_z = float(input("  Z (桌面高度, 米): ") or "0.0")
    except (EOFError, ValueError):
        print("  使用默认值: origin=(0.15, 0.0, 0.0)")
        origin_x, origin_y, origin_z = 0.15, 0.0, 0.0

    desktop_data = {
        "origin": [origin_x, origin_y, origin_z],
        "square_length": SQUARE_LENGTH,
        "squares_x": SQUARES_X,
        "squares_y": SQUARES_Y,
    }

    print(f"\n  板原点: ({origin_x:.3f}, {origin_y:.3f}, {origin_z:.3f})")
    print("  按 's' 拍摄并计算桌面单应性, 'q' 退出")

    H = None
    while True:
        frame = cam.read()
        if frame is None:
            continue

        charuco_corners, charuco_ids, marker_corners, marker_ids = detector.detect(frame)

        if charuco_corners is not None and charuco_ids is not None:
            display = detector.draw(frame, charuco_corners, charuco_ids,
                                    marker_corners, marker_ids)
            cv2.putText(display, "PRESS 's' TO CALIBRATE DESKTOP",
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        else:
            display = frame
            cv2.putText(display, "No board detected",
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        cv2.imshow("Desktop Calibration", cv2.resize(display, (640, 640)))
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('s') and charuco_corners is not None and charuco_ids is not None:
            # 构建 2D-3D 对应关系
            board_obj_points, board_ids = detector.get_board_points()

            pixel_pts = []
            world_pts = []

            for i, cid in enumerate(charuco_ids.flatten()):
                if cid in board_ids.flatten():
                    idx = np.where(board_ids.flatten() == cid)[0][0]
                    # 世界坐标 (以板原点为中心)
                    obj = board_obj_points[idx].flatten()
                    wx = origin_x + obj[0]
                    wy = origin_y + obj[1]
                    wz = origin_z  # 桌面平面 Z
                    world_pts.append([wx, wy])

                    px = charuco_corners[i].flatten()
                    pixel_pts.append(px)

            pixel_pts = np.array(pixel_pts, dtype=np.float32)
            world_pts = np.array(world_pts, dtype=np.float32)

            # 计算单应性
            H, mask = cv2.findHomography(pixel_pts, world_pts, method=cv2.RANSAC)
            inliers = mask.sum() if mask is not None else 0
            print(f"\n  单应性矩阵 ({inliers}/{len(pixel_pts)} inliers):")
            print(f"  {H}")

            # 测试: 用图像中心反算世界坐标
            center_pixel = np.array([640, 640, 1.0])
            center_world = H @ center_pixel
            center_world = center_world[:2] / center_world[2]
            print(f"  验证: 像素(640,640) → 世界({center_world[0]:.4f}, {center_world[1]:.4f})m")

            # 保存
            desktop_data["homography"] = H.tolist()
            with open("desktop_calib.json", 'w') as f:
                json.dump(desktop_data, f, indent=2)
            print(f"  桌面标定已保存: desktop_calib.json")
            break

    cam.release()
    cv2.destroyAllWindows()

    if H is not None:
        print(f"\n  标定完成！在 VLA 中使用:")
        print(f"    transforms.calibrate_desktop_homography(pixel_pts, world_pts)")
        print(f"    x, y = transforms.pixel_to_base_homography(u, v)")


# ============================================================
# 模式3: 实时预览
# ============================================================
def mode_live():
    print("ChArUco 实时检测 — 按 'q' 退出")
    cam = CameraCapture()
    detector = CharucoDetector()

    while True:
        frame = cam.read()
        if frame is None:
            continue

        charuco_corners, charuco_ids, marker_corners, marker_ids = detector.detect(frame)
        display = detector.draw(frame, charuco_corners, charuco_ids,
                                marker_corners, marker_ids)

        if charuco_corners is not None and charuco_ids is not None:
            n = len(charuco_corners)
            cv2.putText(display, f"Charuco: {n} corners", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        cv2.imshow("Charuco Live", cv2.resize(display, (640, 640)))
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cam.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("可用模式: calib | desktop | live")
        sys.exit(0)

    mode = sys.argv[1]
    if mode == "calib":
        mode_calib()
    elif mode == "desktop":
        mode_desktop()
    elif mode == "live":
        mode_live()
    else:
        print(f"未知模式: {mode}")
