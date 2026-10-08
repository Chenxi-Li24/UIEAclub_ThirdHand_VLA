"""
FastUMI Ego STD 相机标定演示
用法:
  python calibrate.py v4l2      # V4L2 方式测试 RGB 取流
  python calibrate.py aruco     # ArUco 实时检测 + 位姿估计
  python calibrate.py charuco   # ChArUco 板标定采图
  python calibrate.py check     # 验证标定参数
"""

import sys
import os
import numpy as np
import cv2

from camera_params import RGB_SEUCM, TOF_PDCM, RGB_EXTRINSIC, TOF_EXTRINSIC
from seucm_model import SEUCMModel
from aruco_detect import ArUcoDetector, CharucoBoardDetector
from coordinate_transform import (
    pose_from_rvec_tvec, invert_pose, apply_transform,
    print_pose, rotmat_from_rvec
)


def demo_v4l2_rgb():
    """V4L2 方式读取 RGB 图像 (基础版)"""
    print("=== V4L2 RGB 取流测试 ===")
    print("依赖 FastUMI_Camera_Steam/readimage.py")
    print()

    # 检查可用的 video 设备
    for i in range(4):
        dev = f"/dev/video{i}"
        if os.path.exists(dev):
            cap = cv2.VideoCapture(i)
            cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
            # 尝试设置 YU12 格式
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YU12'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)

            actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
            fourcc_str = "".join([chr((actual_fourcc >> 8 * i) & 0xFF) for i in range(4)])
            print(f"  {dev}: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}×"
                  f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}, "
                  f"FOURCC={fourcc_str}")

            cap.release()

    print()
    print("请使用以下命令测试实时取流:")
    print("  cd FastUMI_Camera/FastUMI_Camera_Steam")
    print("  python3 readimage.py")


def demo_aruco_realtime():
    """ArUco 实时检测"""
    print("=== ArUco 实时检测 ===")
    print("确保画面内有 ArUco marker (默认 DICT_4X4_50)")
    print("按 'q' 退出, 's' 保存当前帧")
    print()

    from aruco_detect import demo_realtime
    demo_realtime()


def demo_charuco_capture():
    """ChArUco 板标定图像采集"""
    print("=== ChArUco 标定图像采集 ===")
    print("用 ChArUco 板在不同角度拍照，用于重新标定相机内参")
    print("按 's' 保存图像, 按 'q' 退出")
    print()

    board = CharucoBoardDetector(squares_x=5, squares_y=7,
                                 square_length=0.04, marker_length=0.02)

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1280)

    save_dir = "calib_images"
    os.makedirs(save_dir, exist_ok=True)
    count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        charuco_corners, charuco_ids, marker_corners, marker_ids = board.detect(frame)

        if marker_ids is not None:
            frame = cv2.aruco.drawDetectedMarkers(frame, marker_corners, marker_ids)
            if charuco_corners is not None and charuco_ids is not None:
                frame = cv2.aruco.drawDetectedCornersCharuco(
                    frame, charuco_corners, charuco_ids
                )
                quality = f"ChArUco: {len(charuco_corners)} corners"
            else:
                quality = f"Markers: {len(marker_ids)} (need 4+ for ChArUco)"
        else:
            quality = "No markers detected"

        cv2.putText(frame, f"Saved: {count} | {quality}",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        cv2.imshow("ChArUco Capture", frame)
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('s') and charuco_corners is not None:
            path = os.path.join(save_dir, f"charuco_{count:04d}.png")
            cv2.imwrite(path, frame)
            print(f"  已保存: {path} ({len(charuco_corners)} ChArUco corners)")
            count += 1

    cap.release()
    cv2.destroyAllWindows()
    print(f"\n共保存 {count} 张标定图像到 {save_dir}/")


def demo_verify_params():
    """验证标定参数"""
    print("=" * 60)
    print("Lumos Ego STD 标定参数验证")
    print(f"设备 SN: 250801DR48FB26001402")
    print("=" * 60)

    # SEUCM 模型
    seucm = SEUCMModel()
    hfov, vfov = seucm.get_fov()
    print(f"\n📷 RGB 相机 (SEUCM):")
    print(f"  分辨率: {RGB_SEUCM['w']}×{RGB_SEUCM['h']}")
    print(f"  fx={RGB_SEUCM['fx']:.3f}, fy={RGB_SEUCM['fy']:.3f}")
    print(f"  u0={RGB_SEUCM['u0']:.3f}, v0={RGB_SEUCM['v0']:.3f}")
    print(f"  eu={RGB_SEUCM['eu']:.3f}, ev={RGB_SEUCM['ev']:.3f}")
    print(f"  alpha={RGB_SEUCM['alpha']:.6f}, beta={RGB_SEUCM['beta']:.6f}")
    print(f"  估算 FOV: HFOV={hfov:.1f}°, VFOV={vfov:.1f}°")
    print(f"  外参 R (3×3):\n    {np.array(RGB_EXTRINSIC['R']).reshape(3,3)}")
    print(f"  外参 T: {RGB_EXTRINSIC['T']}")

    print(f"\n📏 ToF 深度相机 (PDCM):")
    print(f"  分辨率: {TOF_PDCM['w']}×{TOF_PDCM['h']}")
    print(f"  fx={TOF_PDCM['fx']:.3f}, fy={TOF_PDCM['fy']:.3f}")
    print(f"  u0={TOF_PDCM['u0']:.3f}, v0={TOF_PDCM['v0']:.3f}")
    print(f"  distor={TOF_PDCM['distor']}")
    print(f"  外参 T: {TOF_EXTRINSIC['T']}")

    # 测试投影
    print(f"\n🔬 投影测试:")
    # 中心方向
    center = np.array([[0.0, 0.0, 1.0]])
    pixel, valid = seucm.project(center)
    print(f"  正前方 1m → 像素 ({pixel[0,0]:.1f}, {pixel[0,1]:.1f})")

    # 反投影
    ray, valid = seucm.unproject(np.array([[640, 640]]))
    print(f"  像素中心(640,640) → 方向 [{ray[0,0]:.4f}, {ray[0,1]:.4f}, {ray[0,2]:.4f}]")

    # 验证一致性
    test_points_3d = np.array([
        [0.0, 0.0, 1.0],     # 正前方 1m
        [0.3, 0.0, 0.8],     # 右方
        [-0.3, 0.0, 0.8],    # 左方
        [0.0, 0.3, 0.8],     # 上方
        [0.0, -0.3, 0.8],    # 下方
    ])
    print(f"\n  投影→反投影一致性检查:")
    for pt_3d in test_points_3d:
        pixel_2d, valid = seucm.project(pt_3d.reshape(1, 3))
        if valid[0]:
            ray_3d, _ = seucm.unproject(pixel_2d)
            # 比较方向
            dir_orig = pt_3d / np.linalg.norm(pt_3d)
            dir_recov = ray_3d[0]
            angle_err = np.arccos(np.clip(np.dot(dir_orig, dir_recov), -1, 1))
            print(f"    {pt_3d} → 像素{pixel_2d[0]} → 角度误差={np.degrees(angle_err):.4f}°")

    print(f"\n✅ 标定参数验证完成")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "v4l2":
        demo_v4l2_rgb()
    elif cmd == "aruco":
        demo_aruco_realtime()
    elif cmd == "charuco":
        demo_charuco_capture()
    elif cmd == "check":
        demo_verify_params()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
