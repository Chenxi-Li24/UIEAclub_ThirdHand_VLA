# 最终技术决策

## 选择

采用“架构 A 建基础、架构 B 为交付目标”的渐进路线。第一轮实现只包含相机/几何/融合/跟踪/对象记忆/安全 gate 的离线核心与 Dry Run 数据合同，不连接、不移动机械臂。实例分割模型在同一 Lumos 回放集完成 benchmark 后再选；优先评估 Apache-2.0 的 RTMDet-tiny-ins，当前 YOLOv8n 只作基线。

## 固化的技术约束

- Lumos 是唯一主 RGB；D435 只提供临时深度，RGB 只作调试/标定/回退。
- D435 点云先在其 optical frame 生成，再经固定外参和 SEUCM 投影到 Lumos；不使用 bbox 中心深度。
- Lumos camera model 默认为 SEUCM/EUCM，须通过独立验证；现有 107.95 px 标定隔离。
- 所有姿态使用明确坐标方向的 4×4 SE(3)；Startouch RPY 使用 `Rz*Ry*Rx`。
- 相机无硬同步时只在 stop-and-look 条件下生成候选。
- track id 不是 object identity；base-frame ObjectMemory 带 covariance、TTL 和 ambiguity。
- 任何 stale/ambiguous/low-coverage/invalid-calibration 目标都 fail closed。
- VLM 不进入实时安全回路，也不能直接调用执行器。
- 真实执行必须由独立 `RobotExecutor`、人工批准和安全状态机共同开启；本轮不实现真实动作调用。

## 近期模型决策

当前“视觉模型”是 YOLOv8n COCO detect、CPU、320×240、每 10 帧一次，不满足最终需求。短期不盲换模型：先建立回放和指标；之后比较：

1. YOLOv8n baseline（当前）
2. YOLO nano segmentation（许可允许的研究基线）
3. RTMDet-tiny-ins（推荐可分发候选）
4. Mask R-CNN R50-FPN（精度基线）

开放词汇 GroundingDINO+SAM2 与 FoundationPose 属于架构 C，不阻塞 B。

## 为什么不直接执行抓取

现有系统同时存在错误姿态换算、无效手眼标定、忽略实测深度、短期 IoU 跟踪和可被无关事件推进的 P0 状态机。修复网页按钮并不能使抓取安全，反而可能让原本未到达 backend 的命令开始触发真实动作。因此先断开业务代码与执行器，完成离线可证明链条。

## 下一次人工 gate

只有以下证据齐全才请求用户进行标定/实机测试：

- 纯离线测试和回放 benchmark 报告通过；
- Lumos 内参、双相机外参、手眼和全链独立验证通过；
- Dry Run UI 能显示 exact candidate、误差/协方差、拒绝原因和版本；
- 状态机故障注入无法绕过批准；
- 用户确认急停、工作区清空、低速、安全高度和逐阶段测试流程。

