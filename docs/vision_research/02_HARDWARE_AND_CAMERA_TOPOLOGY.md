# 硬件与相机拓扑

## 物理关系

Lumos Touch R1 是 6-DoF 桌面机械臂。Lumos/XVisio 鱼眼 RGB 与 Intel RealSense D435 均安装在末端，D435 位于 Lumos 上方。两者属于 eye-in-hand 组合：机械臂运动时两相机共同运动，但有固定刚体外参。

目标坐标链：

```text
D435 depth optical --T_lumos_from_d435--> Lumos optical
Lumos optical      --T_flange_from_lumos--> flange
flange             --T_base_from_flange(t)--> robot base
```

所有变换采用“目标坐标系 from 源坐标系”的命名，4×4 齐次矩阵，右手系，平移单位米。任何 ROS `camera_link` 与 optical frame 的轴约定必须在适配器处显式转换，不能靠命名猜测。

## 设备稳定标识

| 设备 | USB ID | 序列号 | 稳定路径/接口 |
|---|---|---|---|
| XVisio/Lumos | `040e:f408` | `250801DR48FB26001402` | `/dev/v4l/by-id/usb-XVisio_Technology_XVisio_vSLAM_...-video-index0` |
| RealSense D435 | `8086:0b07` | `345423023197` | pyrealsense2 serial selection |
| Startouch | CAN | N/A | `can0`, 1 Mbps，当前由已有 bridge 独占 |

相机打开必须按序列号/by-id，不使用 `/dev/video0` 或“第一个 RealSense”作为生产选择器。

## Lumos RGB

- 原始目标格式：1280×1280，YU12/I420，可达 100 fps（实际值需测量）。
- 厂商仓库提供 `rgb_intrinsic_SEUCM.txt`，说明相机原生模型为 SEUCM/EUCM。
- 现有设备参数约 `fx=fy=392.168, cx=637.761, cy=640.597, alpha=0.678979, beta=0.749026`，仅作为待验证候选，不直接进入执行。
- 厂商 `FastUMI_Camera` 与 `FastUMI_Hardware_SDK` 仓库没有根 LICENSE；代码/二进制再分发权不明确。

## D435 深度

- 主用途：生成 D435 depth optical 坐标系点云，然后投影到 Lumos RGB。
- D435 RGB 只用于 D435 内部 depth-to-color 对齐、调试、时序/外参标定和故障回退，不作为主语义图像。
- Intel 官方规格：主动双目，深度 FOV 约 85.2°×58°，标称工作范围约 0.3–3 m。近距离、反光、透明、纹理弱和遮挡边界需视为低置信度。
- 深度值是相机光轴 Z，不是沿单位视线的欧氏距离。

## 同步策略

Lumos 与 D435 没有共同硬件触发。在线融合必须记录：

- 各自设备时间戳、主机单调时间、帧号
- 采集队列长度与帧龄
- `T_base_from_flange` 的采样时间
- 两帧最大允许时间差
- 机械臂速度/是否静止

Phase 1 采用 stop-and-look：只在机械臂静止、RGB/depth 年龄与时间差均在门限内时生成抓取候选。运动中可继续显示跟踪，但候选状态必须是 `STALE` 或 `UNSAFE`。

## 电源与进程约束

- 不在应用启动时执行 sudo、写 sysfs、改 autosuspend 或 reset USB。
- 相机服务单实例并持有显式锁；健康检查不得通过打开第二条 RealSense pipeline 实现。
- 进程所有权清晰：父服务负责启动、监控和回收子进程；禁止孤立流进程。
- CAN bridge 与视觉服务解耦。视觉离线测试不导入或初始化 Startouch SDK。
