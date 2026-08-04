# Offline Vision Safety Core — Implementation Results

记录日期：2026-08-04（Asia/Shanghai）  
Ubuntu 项目：`/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place`  
实现分支：`codex/vision-safety-core-20260804`  
审计基线：`1fe9da3d2256`

## 本轮结果

已新增一个与硬件隔离的纯 Python 视觉安全核心，覆盖：

- 冻结且带校验的帧时间戳、标定 ID、位姿协方差、追踪状态和 Dry Run 报告；
- SDK RPY 约定的 `Rz(yaw) @ Ry(pitch) @ Rx(roll)` 与 SE(3) 变换；
- D435 pinhole 轴向 Z 深度模型与 Lumos SEUCM 投影/反投影；
- D435 点云变换到 Lumos 后的最近表面 z-buffer；
- 带类别、距离、协方差、时间和标定门控的 3D Hungarian 追踪；
- 有容量、过期、不确定度、命中数和标定失效规则的 robot-base 对象记忆；
- 标定、帧龄、协方差、点云数量、工作区、可达性和碰撞结果的 fail-closed 门禁；
- 只包含几何候选和拒绝原因、没有任何执行传输字段的 Dry Run 报告；
- 严格 JSON/NPZ manifest 解析、确定性回放指标和原子 JSON 导出。

本轮没有修改 `proxy.js`、`camera_bridge.py`、Startouch bridge、网页抓取按钮或既有标定文件，也没有把新模块接入正在运行的服务。

## 测试证据

测试环境：

- Python `3.10.20`（现有 `LumosTouch` Conda 环境）
- NumPy `2.2.6`
- SciPy `1.15.3`
- pytest `8.4.2`
- pytest-asyncio `0.26.0`
- pytest 依赖临时放在 `/tmp/thirdhand-vision-test-deps`，未改 Conda 或系统配置

执行命令：

```bash
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place/web-control/server
PYTHONPATH=/tmp/thirdhand-vision-test-deps:. \
  /home/nieqingcao/miniconda3/envs/LumosTouch/bin/python \
  -m pytest tests/vision -v --durations=10
```

结果：`84 passed in 0.21s`，0 failure，0 warning。

覆盖的关键回归包括：

- 复合 RPY 不得使用 Rodrigues 向量解释；
- SEUCM 中心光线、有效域、反投影往返；
- D435 Z 深度不得当作欧氏距离；
- z-buffer 必须保留最近 Lumos 表面并统计遮挡源点；
- 追踪不得因单帧漏检立即清空，不得跨类别或跨标定关联；
- 时间倒退、未来帧、标定变化、越界和过期全部拒绝；
- Dry Run 在所有已列安全故障下均拒绝；
- 核心源码 AST 中没有 `can`、`pyrealsense2`、`socket`、`startouch`、`subprocess` 或 `websocket` 导入，也没有动作 API 关键字。

原项目基线测试没有作为通过证据：Ubuntu 系统 pytest 位于 Python 3.8，而项目 `pyproject.toml` 要求 Python ≥3.10，收集时在 `tuple[...]` 类型注解处失败。没有为了绕过该问题修改系统 Python 或项目依赖。

## 合成回放结果

manifest：`web-control/server/tests/vision/fixtures/synthetic_replay.json`  
metrics SHA-256：`220ef79e6a5810ba5c42a07ac7b02739f5065980020006e76927056cc6c7b7a7`

两次独立执行的 JSON 经 `cmp` 字节完全相同：

| 指标 | 结果 |
|---|---:|
| frames | 3 |
| registration coverage | 0.75 |
| valid target-cloud frames | 1 |
| ID switches | 0 |
| track continuity | 1.0 |
| fixture latency P50/P95 | 20.0 / 29.0 ms |
| Dry Run approvals/rejections | 1 / 2 |
| Dry Run approval rate | 0.3333333333 |

这只是用于验证指标代码和确定性的合成 fixture，不代表真实相机精度、识别率或抓取成功率。

## 深度注册微基准

输入为全有效的合成 `848×480` D435 Z-depth，输出为 `1280×1280` Lumos 图，单位变换，CPU 上预热 2 次后测量 5 次：

- 单帧耗时：`125.272, 130.894, 118.926, 126.085, 120.046 ms`
- P50：`125.272 ms`
- P95：`129.932 ms`
- 输入有效像素：`407040`
- z-buffer 后输出有效像素：`242158`

该纯 NumPy 基准低于研究计划中的合成核心 `300 ms` P95 预算，但不包含相机采集、同步、检测/分割、robot-base 变换和网页显示，因此不能据此宣布端到端实时性达标。

## 当前在线视觉模型

正在运行的既有路径仍是 `web-control/server/camera_bridge.py` 的 `yolov8n.pt`：Ultralytics YOLOv8 nano、COCO 检测权重、CPU、D435 RGB `320×240`、`imgsz=320`、`conf=0.25`、每 10 帧推理一次，约 3 Hz；它不是实例分割模型，且当前没有在 Lumos RGB 上检测。新安全核心尚未接入在线检测。

## 仍未通过的人工门禁

以下项目未执行，也不能用本轮合成结果替代：

1. Lumos SEUCM 内参重新采集与独立留出验证；现有 ChArUco RMS `107.9468 px` 继续隔离。
2. D435→Lumos 外参与相机→机器人外参重新标定、方向/单位检查和独立静态验证。
3. 同步 Lumos RGB、D435 depth、姿态和时间戳的真实只读回放数据采集。
4. 检测/实例分割 recall、mask 点云纯度、深度对齐 P50/P95、base-frame jitter、遮挡重关联与误合并基准。
5. 在线 Dry Run 叠加层、IK 和碰撞检查器的只读接入。
6. 用户现场逐级批准的预抓取安全高度、接近不闭合、低速单物体抓取和放置测试。

在上述门禁全部通过并获得新的明确授权前，真实运动保持禁止。

