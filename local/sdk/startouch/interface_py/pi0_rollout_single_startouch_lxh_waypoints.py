#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件用途：
    该文件用于单臂 startouch 的在线策略回放控制：采集一路 YU12 摄像头图像与单臂状态，
    调用远程 policy server 推理动作，再将动作下发到机械臂与夹爪执行。

主要功能：
    1. 以 YU12(I420) 模式初始化摄像头并转为 RGB 图像。
    2. 读取单臂末端位姿（SDK 为法兰；若训练标签为夹爪尖 TCP，则用 --tcp_offset 与训练对齐）、
       四元数与夹爪开合（0~1），组装策略输入观测 obs。
    3. 通过 websocket 调用策略服务获取动作序列。
    4. 解析单臂 7 维动作（xyz + RPY + gripper），转为关节 waypoints 后发送给 startouch 执行。

适用场景：
    1. 真机部署时的单臂策略联调与在线回放。
    2. 已有远程策略服务（serve_policy）并需要实时闭环执行的场景。
    3. 需要验证视觉输入 + 机器人状态联合推理效果的场景。

核心逻辑：
    启动后先连接机器人（via CAN）、策略服务器与摄像头，循环中持续读取当前机器人状态与图像，
    将其打包后发送到策略服务器获取动作序列，再按组求 IK 并调用 move_joint_waypoints 执行。

运行方式：
    sudo ip link set can0 up type can bitrate 1000000
    PYTHONPATH=/home/lumos/openpi/startouch_sdk/interface_py

    python pi0_rollout_single_startouch_lxh_waypoints.py \
        --description "Pick the target sponge and place it in the target slot in the grid"

    uv run pi0_rollout_single_startouch_lxh_waypoints.py \
        --description "Pick up the pink mug from the three mugs on the table with your right hand and place it on the round, off-white coaster in front of your right hand."

运行前提：
    1. Python >= 3.8。
    2. 已安装依赖：opencv-python、numpy、scipy、openpi_client、startouchclass。
    3. startouchclass 中 SingleArm 可正常导入。
    4. CAN 总线可达，且策略服务在 SERVER_IP:PORT 正常运行。
    5. 摄像头设备节点存在（默认 /dev/video0）。

参数说明：
    --description
        含义：任务自然语言描述，会直接传给策略服务作为 prompt。
        类型：字符串
        是否必填：是

    --can
        含义：单臂对应的 CAN 接口名。
        类型：字符串
        是否必填：否
        默认值：can0

    --camera_dev
        含义：摄像头设备编号，对应 /dev/videoN 中的 N。
        类型：整数
        是否必填：否
        默认值：0

    --speed_percent
        含义：move_joint_waypoints 的速度比例，归一化输入。
        类型：浮点数
        是否必填：否
        默认值：0.3

注意事项：
    1. 当前 SERVER_IP/PORT、摄像头分辨率为硬编码参数，部署前请按现场环境确认。
    2. 该脚本会直接驱动真机运动，建议在安全区域、低速和有人监护条件下调试。
    3. 策略返回的动作中 RPY 为度；脚本会转为弧度再下发，与 SDK 读写的欧拉角（弧度）一致。
"""

import argparse
import datetime
import os
import select
import subprocess
import sys
import termios
import tempfile
import textwrap
import time
import tty

import cv2
import numpy as np
from PIL import Image

from openpi_client import websocket_client_policy, image_tools

from startouchclass import SingleArm, euler_to_quaternion
from tcp_compensation import (
    flange_position_to_tcp,
    parse_tool_offset_xyz,
    tcp_position_to_flange,
)

# ====== 本机 policy server 参数 ======
SERVER_IP = "180.184.74.93"   # 中转服务器ip地址
# SERVER_IP = "127.0.0.1"   # 本地ip地址
PORT = 8002               # DevA=8002、DevB=8003、DevC=8004、DevD=8005、本地=8001

# ====== 摄像头（YU12 / I420）参数 ======
DEV = 0                   # /dev/video0
W, H, FPS = 1280, 1280, 100


def mask_to_rgb(mask: np.ndarray) -> np.ndarray:
    """将单通道二值 mask 转为 3 通道 RGB。"""
    mask = np.asarray(mask, dtype=np.uint8)
    if mask.ndim == 2:
        mask = mask[..., None]
    if mask.ndim == 3 and mask.shape[-1] == 1:
        return np.repeat(mask, 3, axis=-1)
    if mask.ndim == 3 and mask.shape[-1] == 3:
        return mask
    raise ValueError(f"Unsupported mask shape: {mask.shape}")


def pick_point_from_image_subprocess(
    image_rgb: np.ndarray, window_name: str = "pick_point_subprocess"
) -> tuple[int, int]:
    """在独立子进程里用 OpenCV 鼠标点选，避免主进程被 HighGUI 段错误拖崩。"""
    with tempfile.NamedTemporaryFile(prefix="pick_point_", suffix=".png", delete=False) as tf:
        image_path = tf.name
    try:
        bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        if not cv2.imwrite(image_path, bgr):
            raise RuntimeError(f"无法写入临时图像: {image_path}")

        child_code = textwrap.dedent(
            """
            import cv2
            import sys

            img_path = sys.argv[1]
            win = sys.argv[2]
            img = cv2.imread(img_path, cv2.IMREAD_COLOR)
            if img is None:
                print("ERROR:read_image_failed", file=sys.stderr)
                sys.exit(2)

            clicked = {"pt": None}
            def on_mouse(event, x, y, _flags, _param):
                if event == cv2.EVENT_LBUTTONDOWN:
                    clicked["pt"] = (int(x), int(y))
                    print(f"CLICK:{int(x)},{int(y)}", flush=True)
                    canvas = img.copy()
                    cv2.circle(canvas, clicked["pt"], 4, (0, 0, 255), -1)
                    cv2.imshow(win, canvas)

            cv2.namedWindow(win, cv2.WINDOW_NORMAL)
            cv2.setMouseCallback(win, on_mouse)
            cv2.imshow(win, img)
            print("[INFO] 请在图像窗口左键点击目标点（按 q 可退出）", flush=True)
            while clicked["pt"] is None:
                key = cv2.waitKey(20) & 0xFF
                if key == ord("q"):
                    cv2.destroyWindow(win)
                    print("CANCELLED", file=sys.stderr)
                    sys.exit(3)
            x, y = clicked["pt"]
            cv2.destroyWindow(win)
            print(f"{x},{y}", flush=True)
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", child_code, image_path, window_name],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            text = proc.stdout.strip().splitlines()
            if not text:
                raise RuntimeError("子进程未返回点坐标")
            for line in text:
                if line.startswith("CLICK:"):
                    click_xy = _parse_xy_pair(line.split("CLICK:", 1)[1], "子进程点击日志")
                    print(f"[INFO] 鼠标点击坐标: {click_xy}")
            return _parse_xy_pair(text[-1], "子进程点选返回值")
        if proc.returncode == 3:
            raise KeyboardInterrupt("用户取消点选")
        raise RuntimeError(
            "子进程点选失败: "
            f"returncode={proc.returncode}, stdout={proc.stdout!r}, stderr={proc.stderr!r}"
        )
    finally:
        try:
            os.remove(image_path)
        except OSError:
            pass


def _parse_xy_pair(s: str, source_name: str) -> tuple[int, int]:
    """解析 'x,y' 坐标字符串。"""
    text = str(s).strip()
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 2:
        raise ValueError(f"{source_name} 需要 'x,y' 两个整数，实际得到: {s!r}")
    try:
        x = int(parts[0])
        y = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"{source_name} 需要整数坐标，实际得到: {s!r}") from exc
    return x, y


def show_mask_preview_subprocess(
    image_rgb: np.ndarray,
    mask_1c: np.ndarray,
    point_xy=None,
    overlay_window: str = "sam3_mask_overlay",
    mask_window: str = "sam3_mask",
) -> None:
    """在独立子进程显示 SAM3 分割结果，并等待按 y 确认后继续。"""
    mask_1c = np.asarray(mask_1c, dtype=np.uint8)
    if mask_1c.ndim == 3:
        mask_1c = mask_1c[..., 0]
    mask_bool = mask_1c > 0

    overlay = image_rgb.copy()
    if np.any(mask_bool):
        red = np.array([255, 0, 0], dtype=np.uint8)
        overlay[mask_bool] = (
            0.5 * overlay[mask_bool].astype(np.float32) + 0.5 * red.astype(np.float32)
        ).astype(np.uint8)

    if point_xy is not None:
        px, py = int(point_xy[0]), int(point_xy[1])
        cv2.circle(overlay, (px, py), 4, (0, 255, 0), -1)

    with tempfile.NamedTemporaryFile(prefix="sam3_overlay_", suffix=".png", delete=False) as tf1:
        overlay_path = tf1.name
    with tempfile.NamedTemporaryFile(prefix="sam3_mask_", suffix=".png", delete=False) as tf2:
        mask_path = tf2.name

    try:
        if not cv2.imwrite(overlay_path, cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR)):
            raise RuntimeError(f"无法写入临时叠加图: {overlay_path}")
        if not cv2.imwrite(mask_path, mask_1c):
            raise RuntimeError(f"无法写入临时 mask 图: {mask_path}")

        child_code = textwrap.dedent(
            """
            import cv2
            import sys

            overlay_path = sys.argv[1]
            mask_path = sys.argv[2]
            overlay_win = sys.argv[3]
            mask_win = sys.argv[4]

            overlay = cv2.imread(overlay_path, cv2.IMREAD_COLOR)
            mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
            if overlay is None or mask is None:
                print("ERROR:read_preview_image_failed", file=sys.stderr)
                sys.exit(2)

            cv2.namedWindow(overlay_win, cv2.WINDOW_NORMAL)
            cv2.namedWindow(mask_win, cv2.WINDOW_NORMAL)
            cv2.imshow(overlay_win, overlay)
            cv2.imshow(mask_win, mask)
            print("[INFO] 已显示 SAM3 分割结果：按 y 继续，按 q 退出", flush=True)
            while True:
                key = cv2.waitKey(20) & 0xFF
                if key in (ord("y"), ord("Y")):
                    sys.exit(0)
                if key in (ord("q"), ord("Q")):
                    print("CANCELLED", file=sys.stderr)
                    sys.exit(3)
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", child_code, overlay_path, mask_path, overlay_window, mask_window],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return
        if proc.returncode == 3:
            raise KeyboardInterrupt("用户在 mask 预览窗口按 q 退出")
        raise RuntimeError(
            "子进程分割预览失败: "
            f"returncode={proc.returncode}, stdout={proc.stdout!r}, stderr={proc.stderr!r}"
        )
    finally:
        for p in (overlay_path, mask_path):
            try:
                os.remove(p)
            except OSError:
                pass


class Sam3PointSegmenter:
    """SAM3 单点提示分割器。"""

    def __init__(
        self,
        checkpoint_path: str,
        sam3_repo: str,
        device: str = "auto",
        confidence_threshold: float = 0.5,
    ) -> None:
        if sam3_repo and os.path.isdir(sam3_repo) and sam3_repo not in sys.path:
            sys.path.insert(0, sam3_repo)

        import torch
        from sam3 import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor

        self._torch = torch
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device

        self.model = build_sam3_image_model(
            checkpoint_path=checkpoint_path,
            load_from_HF=False,
            device=device,
            eval_mode=True,
        )
        self.processor = Sam3Processor(self.model, confidence_threshold=confidence_threshold)

    def predict_mask_from_point(self, image_rgb: np.ndarray, point_xy) -> np.ndarray:
        """输入 RGB 图与像素点，输出 uint8 二值 mask（0/255）。"""
        h, w = image_rgb.shape[:2]
        x, y = point_xy
        x = int(np.clip(x, 0, w - 1))
        y = int(np.clip(y, 0, h - 1))

        image = Image.fromarray(image_rgb)
        state = self.processor.set_image(image)
        self.processor.reset_all_prompts(state)

        if "geometric_prompt" not in state:
            state["geometric_prompt"] = self.model._get_dummy_prompt()
        if "language_features" not in state["backbone_out"]:
            state["backbone_out"].update(
                self.model.backbone.forward_text(["visual"], device=self.model.device)
            )

        norm_x = x / float(max(w, 1))
        norm_y = y / float(max(h, 1))
        points = self._torch.tensor(
            [[[norm_x, norm_y]]], device=self.model.device, dtype=self._torch.float32
        )
        labels = self._torch.tensor([[1]], device=self.model.device, dtype=self._torch.long)
        state["geometric_prompt"].append_points(points=points, labels=labels)

        state = self.processor._forward_grounding(state)
        if "masks" not in state or int(state["masks"].shape[0]) == 0:
            return np.zeros((h, w), dtype=np.uint8)

        masks_bool = state["masks"][:, 0].detach().cpu().numpy().astype(bool)
        scores = state.get("scores", None)
        boxes = state.get("boxes", None)
        if scores is not None:
            scores = scores.detach().cpu().numpy()
        if boxes is not None:
            boxes = boxes.detach().cpu().numpy()

        print(
            f"[SAM3] 点击点=({x},{y})，返回候选数={masks_bool.shape[0]}，"
            f"mask分辨率={masks_bool.shape[1]}x{masks_bool.shape[2]}"
        )
        areas = []
        contains_flags = []
        for i in range(masks_bool.shape[0]):
            contains_point = bool(masks_bool[i, y, x])
            area = int(masks_bool[i].sum())
            contains_flags.append(contains_point)
            areas.append(area)
            score_txt = "NA" if scores is None else f"{float(scores[i]):.4f}"
            if boxes is None:
                box_txt = "NA"
            else:
                x0, y0, x1, y1 = boxes[i].tolist()
                box_txt = f"[{x0:.1f}, {y0:.1f}, {x1:.1f}, {y1:.1f}]"
            print(
                f"[SAM3][{i:02d}] score={score_txt} contains_point={contains_point} "
                f"area={area} box={box_txt}"
            )

        contains_idx = [i for i, ok in enumerate(contains_flags) if ok]
        if contains_idx:
            # 先按分数降序（若有），再按面积升序，最后按下标升序做稳定决策。
            if scores is not None:
                selected_idx = min(
                    contains_idx,
                    key=lambda i: (-float(scores[i]), int(areas[i]), i),
                )
                print(
                    "[SAM3] 选中候选: idx=%d（包含点击点，分数最高优先，面积最小次优）"
                    % selected_idx
                )
            else:
                selected_idx = min(contains_idx, key=lambda i: (int(areas[i]), i))
                print(
                    "[SAM3] 选中候选: idx=%d（包含点击点，按面积最小）"
                    % selected_idx
                )
        else:
            selected_idx = 0
            print("[SAM3] 无候选包含点击点，回退到 idx=0")

        mask = state["masks"][selected_idx, 0].detach().cpu().numpy()
        mask = (mask > 0).astype(np.uint8) * 255
        return mask


def init_yu12_camera(dev):
    """按 YU12(I420) 模式初始化摄像头。"""
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开 /dev/video{dev}")

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YU12"))  # YU12 == I420
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    # 打印一下驱动返回的实际 FOURCC，确认真的是 YU12
    fcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    fcc = "".join([chr((fcc_int >> (8 * i)) & 0xFF) for i in range(4)])
    print("FOURCC from driver:", fcc)
    return cap


def grab_rgb(cap):
    """
    从 YU12(I420) 摄像头抓一帧，返回 RGB 图像 (H, W, 3, uint8)。
    逻辑：raw(YU12) -> BGR -> RGB
    """
    ok, raw = cap.read()
    if not ok:
        raise RuntimeError("摄像头读取失败")

    # raw 一般是 (H*3//2, W) 或 (H*3//2, W, 1)，统一拉平成 2D 再转
    yuv = np.ascontiguousarray(raw).reshape(H * 3 // 2, W)
    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)   # I420 -> BGR
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)        # BGR -> RGB
    return rgb


def grab_rgb_latest(cap, flush_n=4):
    """丢弃旧帧后抓取最新一帧，并输出 RGB 图像。"""
    for _ in range(flush_n):
        cap.grab()
    ok, raw = cap.read()
    if not ok:
        raise RuntimeError("摄像头读取失败")
    yuv = np.ascontiguousarray(raw).reshape(H * 3 // 2, W)
    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _stdin_read_char_nonblocking():
    """终端模式下非阻塞读一个字符；非 tty 或无可读数据时返回 None。"""
    if not sys.stdin.isatty():
        return None
    r, _, _ = select.select([sys.stdin], [], [], 0)
    if not r:
        return None
    try:
        return sys.stdin.read(1)
    except Exception:
        return None


def _stdin_wants_reset_pause() -> bool:
    ch = _stdin_read_char_nonblocking()
    return ch in ("s", "S")


def reset_arm_to_init(arm: SingleArm, init_pos, init_euler) -> None:
    arm.set_end_effector_pose_euler(pos=init_pos, euler=init_euler, tf=2)
    arm.setGripperPosition(1.0)


def main():
    """主流程：连接设备，循环推理并下发单臂动作。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--description", required=True, help="任务自然语言指令")
    parser.add_argument("--can", default="can0", help="单臂 CAN 接口")
    parser.add_argument("--camera_dev", type=int, default=DEV, help="摄像头设备编号")
    parser.add_argument(
        "--speed_percent",
        type=float,
        default=0.3,
        help="move_joint_waypoints 速度比例，归一化输入；默认 0.3",
    )
    parser.add_argument(
        "--init_pose",
        type=str,
        default="0.3,0.0,0.16,0.0,0.0,0.0",
        help="模拟当前位姿: x,y,z,roll,pitch,yaw（弧度）",
    )
    parser.add_argument(
        "--tcp_offset",
        type=str,
        default="0.0,0.0,0.0",
        help=(
            "法兰系下「法兰原点→夹爪尖 TCP」的平移 x,y,z（米），与训练 TCP 定义一致。"
            "训练 state/action 为 TCP、真机读法兰时填标定；训练为法兰则 0,0,0。"
        ),
    )
    parser.add_argument(
        "--tcp_debug",
        action="store_true",
        help="每一步打印：观测侧 法兰→TCP；chunk 内每一步 策略TCP→下发法兰",
    )
    parser.add_argument(
        "--action_start",
        type=int,
        default=0,
        help="本次推理返回的 action 序列：起始下标（0 起算，含）",
    )
    parser.add_argument(
        "--action_end",
        type=int,
        default=30,
        help="结束下标（0 起算，含）；与 action_start 闭区间，若超出序列长度则截断到末尾",
    )
    parser.add_argument(
        "--sam3_checkpoint",
        type=str,
        default="/home/lumos/.cache/modelscope/hub/models/facebook/sam3/sam3.pt",
        help="SAM3 checkpoint 路径",
    )
    parser.add_argument(
        "--sam3_repo",
        type=str,
        default="/home/lumos/openpi/sam3",
        help="SAM3 仓库路径（用于导入 sam3 包）",
    )
    parser.add_argument(
        "--sam3_device",
        type=str,
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="SAM3 推理设备",
    )
    parser.add_argument(
        "--sam3_conf_thresh",
        type=float,
        default=0.5,
        help="SAM3 置信度阈值",
    )
    args = parser.parse_args()

    tcp_off = parse_tool_offset_xyz(args.tcp_offset)
    if np.any(tcp_off != 0.0):
        print(f"[INFO] TCP 工具偏移（法兰系，米）={tcp_off.tolist()}")

    # ---- 解析初始位姿参数 ----
    def parse_init_pose(s):
        parts = [float(v) for v in s.split(",")]
        if len(parts) != 6:
            raise ValueError(f"init_pose 需要 6 个值 x,y,z,r,p,y，实际得到: {s}")
        x, y, z, roll, pitch, yaw = parts
        return [x, y, z], [roll, pitch, yaw]

    init_pos, init_euler = parse_init_pose(args.init_pose)

    # ---- 初始化机器人 ----
    arm = SingleArm(can_interface_=args.can)
    time.sleep(2)

    # ---- 移动到初始位姿 ----
    print(f"[INFO] 移动到初始位姿: {args.init_pose}")
    arm.set_end_effector_pose_euler(pos=init_pos, euler=init_euler, tf=1)
    arm.setGripperPosition(1.0)
    print("[INFO] 已到达初始位姿")
    print(SERVER_IP, PORT)

    # ---- 连接 policy server（本机）----
    policy_client = websocket_client_policy.WebsocketClientPolicy(
        host=SERVER_IP,
        port=PORT,
    )
    print(f"[INFO] 已连接策略服务器：ws://{SERVER_IP}:{PORT}")

    # ---- 摄像头 ----
    cam = init_yu12_camera(args.camera_dev)
    segmenter = Sam3PointSegmenter(
        checkpoint_path=args.sam3_checkpoint,
        sam3_repo=args.sam3_repo,
        device=args.sam3_device,
        confidence_threshold=args.sam3_conf_thresh,
    )
    selected_point = None

    # 预热
    for _ in range(60):
        _ = cam.read()
    print("[INFO] 摄像头预热完成，开始循环")

    input("按 Enter 开始")

    stdin_fd = sys.stdin.fileno()
    old_term = None
    traj_log_fp = None
    try:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        traj_log_path = os.path.join(os.getcwd(), f"inferenceTraj_{ts}.txt")
        traj_log_fp = open(traj_log_path, "w", encoding="utf-8")
        traj_log_fp.write(
            "# inference trajectory log\n"
            f"# created_at={datetime.datetime.now().isoformat(timespec='seconds')}\n"
            f"# server=ws://{SERVER_IP}:{PORT}\n"
            "# fields: infer_idx, action_step_idx, action_xyzrpyg, cmd_flange_pos, cmd_euler_rad, cmd_gripper\n"
        )
        traj_log_fp.flush()
        infer_idx = 0
        print(f"[INFO] 动作轨迹将写入: {traj_log_path}")

        if sys.stdin.isatty():
            old_term = termios.tcgetattr(stdin_fd)
            tty.setcbreak(stdin_fd)
        print("[INFO] 按 s：机械臂复位到初始位姿并暂停推理；按 c：继续推理")

        paused = False
        while True:
            ch = _stdin_read_char_nonblocking()
            if ch in ("s", "S"):
                reset_arm_to_init(arm, init_pos, init_euler)
                paused = True
                print("[INFO] 已复位到初始位姿，推理已暂停；按 c 继续")
                continue
            if ch in ("c", "C"):
                paused = False
                print("[INFO] 继续推理")

            if paused:
                time.sleep(0.02)
                continue

            # 1. 读取机器人实时状态 --------------------------------------
            # get_ee_pose_quat 返回 (pos_m, quat_wxyz)
            pos, quat_wxyz = arm.get_ee_pose_quat()
            qw, qx, qy, qz = quat_wxyz
            quat = np.array([qx, qy, qz, qw])  # scipy xyzw 格式
            p_tcp = flange_position_to_tcp(pos, quat_wxyz, tcp_off)
            x, y, z = p_tcp

            if args.tcp_debug:
                print(
                    "[TCP DEBUG][obs] flange -> state(TCP) | "
                    f"{np.asarray(pos).round(4)} -> {np.asarray(p_tcp).round(4)} | "
                    f"off {tcp_off.tolist()}"
                )

            gripper_open = float(arm.get_gripper_position())
            # 与 chunk 内夹爪维一致：下发 <0.3 则 −0.25 → 观测送入策略时对 <0.3 读数 +0.2
            gripper_open = float(
                np.clip(
                    np.where(gripper_open < 0.3, gripper_open + 0.2, gripper_open),
                    0.0,
                    1.0,
                )
            )

            # 记录当前位姿（欧拉角单位为弧度），用于后续 action 插值的起点
            cur_pos = arm.get_ee_pose_euler()[0].tolist()
            cur_euler = arm.get_ee_pose_euler()[1].tolist()

            state_vec = np.array([x, y, z, *quat, gripper_open], dtype=np.float32)

            print("[INFO] 机器人状态：", state_vec)

            # 2. 读取摄像头图像（YU12 -> RGB）----------------------------
            img_rgb = grab_rgb_latest(cam)  # (H, W, 3), RGB, uint8

            # resize 到 224x224
            img_rgb = cv2.resize(img_rgb, (224, 224), interpolation=cv2.INTER_AREA)

            # 2.1 选择 point + SAM3 point prompt 分割
            selected_point = pick_point_from_image_subprocess(
                img_rgb, window_name="front_frame_pick_point"
            )
            print(f"[INFO] 本次 point prompt 像素坐标: {selected_point}")
            front_mask_1c = segmenter.predict_mask_from_point(img_rgb, selected_point)
            front_mask_rgb = mask_to_rgb(front_mask_1c)
            show_mask_preview_subprocess(img_rgb, front_mask_1c, point_xy=selected_point)

            # 3. 组装 observation & 远程推理 ----------------------------
            print("state_vec:", state_vec)
            obs = {
                "state": state_vec,
                "image": {
                    "front": image_tools.convert_to_uint8(img_rgb),
                    "front_mask": image_tools.convert_to_uint8(front_mask_rgb),
                },
                "prompt": args.description,
            }

            resp = policy_client.infer(obs)

            # 兼容 "actions" / "action" 两种命名
            if "actions" in resp:
                actions_all = resp["actions"]
            else:
                actions_all = resp["action"]

            # 策略侧可能是只读 numpy / torch，需 copy 后才能原地改夹爪维
            actions_all = np.array(actions_all, dtype=np.float64, copy=True)
            if actions_all.ndim == 1:
                actions_all = actions_all.reshape(1, -1)
            actions_all[..., 6] = np.where(
                actions_all[..., 6] < 0.3,
                actions_all[..., 6] - 0.2,
                actions_all[..., 6],
            )
            actions_all[..., 6] = np.clip(actions_all[..., 6], 0.0, 1.0)

            a0, a1 = args.action_start, args.action_end
            n_act = len(actions_all)
            if a0 < 0 or a1 < 0:
                print(f"[WARN] 忽略非法 action 区间: action_start={a0} action_end={a1}")
                continue
            if a0 > a1:
                print(f"[WARN] action_start 不能大于 action_end: {a0} > {a1}")
                continue
            if n_act == 0:
                print("[WARN] 策略返回的 action 序列为空")
                continue
            lo = a0
            hi = min(a1, n_act - 1)
            if lo >= n_act:
                print(f"[WARN] action_start 越界: start={a0} 序列长度={n_act}")
                continue
            if lo > hi:
                print(f"[WARN] 无 action 可执行: 区间 [{a0},{a1}] 与长度 {n_act} 无交集")
                continue
            action_slice = actions_all[lo : hi + 1]

            # 4. 解析一组 action，求 IK 后一次下发 joint waypoints ----------
            joint_waypoints = []
            cmd_records = []
            q_seed = list(arm.get_joint_positions())
            plan_cancelled = False

            # 日志「第 N 步」的 N 与 actions_all 的下标一致
            for step_idx, action in enumerate(action_slice, start=lo):
                # 规划阶段检测 s 键；轨迹下发后由底层 waypoint 轨迹连续执行。
                if _stdin_wants_reset_pause():
                    reset_arm_to_init(arm, init_pos, init_euler)
                    paused = True
                    plan_cancelled = True
                    print("[INFO] 已复位到初始位姿，推理已暂停；按 c 继续")
                    break

                print(f"第 {step_idx} 步, action:", action)

                # 单臂 action：7 维 [x,y,z,r,p,y,g]
                # rpy 单位：度（策略输出）；下发前转为弧度与 SDK 一致
                x_a, y_a, z_a, roll, pitch, yaw, g_open = action
                g = float(np.clip(g_open, 0.0, 1.0))

                tgt_euler_rad = np.deg2rad([roll, pitch, yaw]).tolist()
                # 策略输出 TCP 目标；SDK 需要法兰位置（随目标姿态旋转的偏移）
                tgt_pos = tcp_position_to_flange(
                    [x_a, y_a, z_a],
                    tgt_euler_rad,
                    tcp_off,
                ).tolist()

                if args.tcp_debug:
                    print(
                        "[TCP DEBUG][cmd] step=%d TCP->flange | "
                        "[%.4f,%.4f,%.4f] -> %s"
                        % (step_idx, x_a, y_a, z_a, tgt_pos)
                    )

                tgt_quat_wxyz = euler_to_quaternion(*tgt_euler_rad)
                q, ok = arm.solve_ik(tgt_pos, tgt_quat_wxyz, q_seed=q_seed)
                if not ok:
                    print(f"[WARN] IK 失败，跳过本轮 waypoint 下发: step={step_idx}")
                    joint_waypoints = []
                    break

                q_seed = list(q)
                joint_waypoints.append(q_seed)
                cmd_records.append(
                    {
                        "step_idx": step_idx,
                        "action": np.asarray(action, dtype=np.float64).tolist(),
                        "tgt_pos": np.asarray(tgt_pos, dtype=np.float64).tolist(),
                        "tgt_euler_rad": np.asarray(tgt_euler_rad, dtype=np.float64).tolist(),
                        "g": g,
                    }
                )

            if plan_cancelled:
                infer_idx += 1
                continue
            if not joint_waypoints:
                infer_idx += 1
                continue

            print(
                "[INFO] 下发 joint waypoints: "
                f"points={len(joint_waypoints)}, speed_percent={args.speed_percent:.3f}"
            )
            arm.set_joint_waypoints(
                joint_waypoints,
                speed_percent=args.speed_percent,
            )

            last_record = cmd_records[-1]
            arm.setGripperPosition(last_record["g"])

            if traj_log_fp is not None:
                for rec in cmd_records:
                    traj_log_fp.write(
                        "infer_idx={infer_idx} step_idx={step_idx} "
                        "action={action_vals} cmd_pos={tgt_pos} cmd_euler_rad={tgt_euler_rad} "
                        "cmd_gripper={g:.6f}\n".format(
                            infer_idx=infer_idx,
                            step_idx=rec["step_idx"],
                            action_vals=rec["action"],
                            tgt_pos=rec["tgt_pos"],
                            tgt_euler_rad=rec["tgt_euler_rad"],
                            g=rec["g"],
                        )
                    )
                traj_log_fp.flush()

            cur_pos = last_record["tgt_pos"]
            cur_euler = last_record["tgt_euler_rad"]
            infer_idx += 1

    finally:
        if traj_log_fp is not None:
            try:
                traj_log_fp.close()
            except OSError:
                pass
        if old_term is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_term)
        cv2.destroyWindow("sam3_mask_overlay")
        cv2.destroyWindow("sam3_mask")
        cv2.destroyWindow("front_frame_pick_point")
        cam.release()
        arm.cleanup()
        print("[INFO] 结束，摄像头与机械臂已释放。")


if __name__ == "__main__":
    main()
