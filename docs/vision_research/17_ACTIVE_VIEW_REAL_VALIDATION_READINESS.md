# 主动视角实机验证就绪审计与标定执行路线

审计时间：2026-08-06（Asia/Shanghai）

## 结论

软件实现、纯函数测试、浏览器测试、确定性回放、故障注入和虚拟 30 分钟浸泡已经完成；当前
**不具备第一次真实观察运动条件**。系统保持正确闭锁，没有创建审批文件，也没有发送机械臂或
夹爪命令。

阻断不是通过修改布尔值可以解决的。缺少的是现场采集并独立验证的几何和路径证据。

## 当前只读证据

| 检查项 | 当前结果 |
|---|---|
| 3000 控制服务 | PID `2761127`，来自另一工作目录；未停止、未重启、未接管 |
| Lumos 服务 | PID `3133769`，端口 3001，健康且帧序列前进 |
| 双相机 Dry Run | PID `3205502`，端口 3100，`STARTOUCH_SIMULATE=1`、占位 CAN、夹爪关闭 |
| D435 | 序列号 `349622074226`，固件 `5.17.3.10`，USB 3.2，RGB-D 在线 |
| 在线执行门 | `robotExecutionEnabled=false`；3100 进程未设置主动观察开启变量，默认关闭 |
| 在线 blockers | `calibration_unavailable`、`robot_pose_unavailable`、`arm_not_stationary`、`task_checkpoint_unvalidated` 等 |
| 活动视角证据目录 | `data/calibration/active-view/` 不存在；没有 `camera.json`、`table.json`、`catalog.json` |
| 观察位 | 没有已验证的预教观察位和路径记录 |
| 任务 checkpoint | 当前仍是官方 COCO RTMDet-Ins tiny，未完成本项目任务数据验收 |

现有历史结果不能补位：`charuco_calib_result.json` 的 RMS 为 `107.9468 px`；旧手眼结果平移
尺度约 `0.32–0.39 m`，与安装物理尺度可疑；历史采集目录只有一份约 3 KiB 的 NPZ。它们继续
隔离，不能写成 `validated:true`。

## 调研后采用的成熟工具

### 1. Lumos EUCM 内参与 Lumos–D435 固定外参：Kalibr

采用 ETH Zurich 的 Kalibr，不自行写标定优化器。Kalibr 官方支持：

- Extended Unified Camera Model（`eucm`），参数正是 `alpha beta fu fv pu pv`，与 Lumos
  SEUCM/EUCM 参数结构相符；
- pinhole、omni、double-sphere 等对照模型；
- 多相机内外参联合标定；
- AprilGrid，且允许标定板部分可见。

采集使用刚性 AprilGrid；打印后必须实测 tag 尺寸和间距，固定在铝板或亚克力板上，保留至少
一个网格宽的白边。拟合与独立验证按姿态分组，至少 20% 图像只用于验证。

### 2. D435：Intel 工厂参数与官方质量工具

D435 当前先保留设备工厂内参、深度标尺和 depth-to-color 外参，通过 `rs-enumerate-devices -c`
记录版本与参数，并用 Intel RealSense Depth Quality Tool 检查平面 fill rate、空间/时间噪声和
绝对距离。Intel 的自标定会修改设备标定表，不能为了消除 blocker 自动运行；只有官方质量检查
证明设备已失准且已备份原表时，才另行决定是否执行 targeted calibration。

### 3. Lumos–flange 手眼：OpenCV 官方 `calibrateHandEye`

复用 OpenCV 官方接口，并同时评估 Tsai、Park、Horaud、Daniilidis，不使用旧自定义 Tsai。
输入方向严格采用官方定义：`T_base_from_gripper` 与 `T_camera_from_target`，输出
`T_gripper_from_camera`。用留出姿态比较靶标在 base 中的一致性，而不是用同一方程自证。

当前在线 Python 环境的 OpenCV 5.0 构建没有导出 `calibrateHandEye`；系统 `/usr/bin/python3`
中的 OpenCV 4.2 提供该接口。标定工具应使用隔离、版本固定且通过合成 AX=XB 测试的环境，不能
改变在线推理环境。

### 4. 项目自有部分只做薄适配与安全审计

项目代码只负责：

- 将 Kalibr/OpenCV/RealSense 输出转换成明确方向的 4×4 SE(3) 和米制单位；
- 计算独立留出集的 median/P95/边缘 P95、桌面平面 P95 和全链静态点 P95；
- 生成内容寻址的 `camera.json`、`table.json`；
- 读取静止机器人姿态，生成未验证观察位采集；
- 由人工逐条验证路径后生成 `catalog.json`；
- 任何源文件变化立即使会话和审批失效。

仓库根目录的 `scripts/calibrate_camera.py` 与 `scripts/teach_points.py` 仍是历史 TODO，占位脚本
不得用于本次验收。活动视角观察位采集应使用已测试的
`web-control/scripts/teach-active-view-pose.js`，目录生成使用
`scripts/vision/finalize_active_view_catalog.py`。

## 现场执行顺序

1. 准备并精确测量刚性 AprilGrid，记录行列、tag 边长、间距比例和打印缩放误差。
2. 在机械臂静止、曝光固定的条件下录制同步 Lumos/D435 标定数据；覆盖中心、四角、鱼眼边缘、
   多距离和多朝向，留出独立验证姿态。
3. 用 Kalibr `eucm-none + pinhole` 路线估计 Lumos 内参和双相机外参；保存原始 bag、目标 YAML、
   报告和版本/提交 ID。
4. 读取 D435 工厂参数并完成官方深度质量检查；不写设备标定表。
5. 在至少 20 个多轴、非共面、停稳姿态上运行 OpenCV 多方法手眼标定，另留姿态验证。
6. 采集桌面平面和独立静态点，只有全部门限通过才生成内容寻址 camera/table evidence。
7. 操作员手动将机械臂放到若干安全观察位；只读脚本采集姿态。每条路径以速度比例不超过
   0.05 单独验证，记录最大关节误差和人工确认。
8. 生成并重新加载 catalog；检查 D435 中央 60% 质量区在桌面上的覆盖多边形。
9. 再运行 simulation/readiness gate。只有这时才向用户展示确切哈希、姿态、路径和一步动作，
   请求第一次真实观察运动授权。

## 必须由用户/现场人员完成的事项

- 提供或制作刚性 AprilGrid，并给出实测尺寸；
- 在每次人工移动、路径预教和真实动作前保证物理急停可达、工作区清空；
- 使用安全假目标，确认桌面和相机安装在采集期间不变化；
- 第一次真实观察运动前，对确切证据哈希、观察位、速度和单步上限明确批准。

## 一手参考

- Kalibr supported models: https://github.com/ethz-asl/kalibr/wiki/supported-models
- Kalibr calibration targets: https://github.com/ethz-asl/kalibr/wiki/calibration-targets
- Kalibr official repository: https://github.com/ethz-asl/kalibr
- OpenCV `calibrateHandEye`: https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html
- Intel RealSense D400 calibration guide: https://dev.realsenseai.com/download/17261/
- librealsense official examples: https://github.com/realsenseai/librealsense/blob/master/examples/readme.md
