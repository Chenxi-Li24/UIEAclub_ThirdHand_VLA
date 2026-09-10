# ThirdHand 当前状态审计

审计时间：2026-08-04（Asia/Shanghai）
审计方式：通过 SSH 别名 `robot-ubuntu` 只读检查；未发送机械臂、夹爪、CAN 或 WebSocket 控制命令，未重启服务，未修改系统配置和标定文件。

## 结论摘要

当前 3000 端口控制页可访问，已有后台进程占用 `can0` 并报告 `armConnected=true`。这不等于视觉抓取已经可用：实际在线检测来自 D435 RGB，Lumos 视频没有接入 3000 服务；主路径没有用 D435 实测深度定位物体；抓取状态机缺少请求关联、超时和失败复位。现有 D435 与 Lumos 手眼标定均不能作为真实运动依据。

## 代码与版本

- 项目：`/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place`
- 分支：`fanxy/fixed-pick-place`
- HEAD：`1fe9da3d2256`
- 工作树：22 个已跟踪文件被修改，另有多项未跟踪脚本、模型和日志；没有 stash。
- 远端：`Oliveirah007/UIEAclub_ThirdHand_VLA`，上游为 `Chenxi-Li24/UIEAclub_ThirdHand_VLA`。
- 项目许可证：MIT；第三方模型和厂商 SDK 需单独审计。

## 主机能力

- Ubuntu 20.04.6，内核 `6.14.6-custom`
- Intel Core i9-14900K，32 逻辑 CPU，31 GiB RAM，无 swap
- NVIDIA RTX 5060 8 GiB，驱动 570.211.01
- Python 运行环境：Ultralytics 8.4.111、Torch 2.13.0+cu130、OpenCV 5.0.0、NumPy 2.5.1、pyrealsense2

## 运行中服务（审计时）

| 端口/进程 | 状态 | 说明 |
|---|---|---|
| `:3000` Node `proxy.js` | HTTP 200 | 主控制页；已有 Startouch bridge 与 D435 bridge 子进程 |
| `:8766` | HTTP 200 | 7 月 30 日遗留 demo，仅 loopback |
| `:8085` | HTTP 200 | 遗留 `ros2_depth_bridge.py`；RGB 已陈旧，深度从未收到 |
| `lumos_stream.py` | 孤立进程 | 不属于 3000 端口 Node 子进程，不能被 `/camera_lumos` 使用 |

`/diag` 显示 `can0` UP、锁 PID 为现有 Startouch bridge、D435 active、`armConnected=true`。`.env` 中 `STARTOUCH_DRY_RUN=0`、`STARTOUCH_SIMULATE=0`，因此当前服务属于真实模式。开发期间不得复用该通道进行任何动作测试。

## 相机拓扑

- Lumos/XVisio：USB `040e:f408`，序列号 `250801DR48FB26001402`，V4L2 `/dev/video0`，1280×1280 YU12 可用；审计时 runtime suspended。
- D435：USB `8086:0b07`，序列号 `345423023197`，USB 3 SuperSpeed，runtime active。
- 两相机均安装在末端执行器上；D435 位于 Lumos 上方。Lumos 仅作为 RGB 相机，不把历史 ToF 字段视为可用传感器。
- 两相机没有已验证的硬件同步。开发阶段采用 stop-and-look：只在机械臂静止且帧龄通过门限时融合。

## 当前视觉模型

`web-control/server/camera_bridge.py` 加载 `yolov8n.pt`：

- Ultralytics YOLOv8 nano，COCO 检测模型（不是实例分割）
- 强制 CPU
- D435 RGB 缩放到 320×240，`imgsz=320`、`conf=0.25`
- 每 10 帧推理一次，约 3 Hz
- 仅保留 bottle、wine glass、cup、spoon、banana、apple；没有 can 类
- Lumos 当前只存在独立 JPEG 流脚本，没有检测

## 已验证的阻塞项

1. `/camera_lumos` 返回 503；`proxy.js` 明确注释掉了 `startLumosStream()`。
2. 主定位函数的正常路径直接与固定桌面平面相交，忽略 D435 bbox 和深度。
3. 机器人返回的是 roll/pitch/yaw，代码却把三元组当 Rodrigues 旋转向量；复合姿态误差离线复现为 13.82° 和 31.46°。
4. D435 标定自定义 Tsai 实现使用了不正确的运动方程并再次反转结果；13 组样本没有独立验证报告。
5. Lumos ChArUco 结果 RMS 107.9468 px，内参明显异常，不能使用。
6. 跟踪仅为贪心 IoU，没有漏检保留、运动模型、类别门控、全局匹配、时间戳和稳定度。
7. 抓取状态机可被任意 `command_complete` 推进，且不检查 `request_id`、`reached`、超时或目标新鲜度。
8. 用户点击 Grasp 时后台日志没有收到 `grasp_object`；“浏览器缓存”尚未被证实为根因。

## 安全基线

- 研究、离线测试和录制回放代码可以继续。
- 任何机械臂动作、夹爪动作、CAN 初始化、服务重启、udev/USB 电源写入、标定覆盖都需要用户现场确认。
- 旧标定文件只作为 `quarantined` 输入保存；执行路径必须拒绝未通过验证门限的标定。
