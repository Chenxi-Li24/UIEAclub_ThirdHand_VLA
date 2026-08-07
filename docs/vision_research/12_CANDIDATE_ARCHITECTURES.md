# 候选架构

## 共同接口

三种架构都必须遵循同一数据流与安全边界：

```text
CameraSource -> FrameSynchronizer -> CameraModel/Transforms
-> Detector/Segmenter -> Tracker -> DepthRegistrar
-> ObjectMemory -> GraspPlanner -> SafetyEvaluator
-> DryRunController -> HumanApproval -> (future) RobotExecutor
-> OutcomeVerifier -> EventStore
```

相机、深度、标定、追踪、抓取和执行通过不可变消息传递。`RobotExecutor` 是唯一允许导入 Startouch SDK 的模块；默认构建和测试不实例化它。

## 架构 A：最小可用几何基线

### 数据流

Lumos RGB 原生 SEUCM -> 当前 YOLOv8n box -> 轻量 2D/3D tracker -> D435 点云投影到 Lumos -> bbox 内保守中心区域/前景 cluster -> top-down 几何候选 -> Dry Run JSON/UI。

### 算法与资源

- 继续用当前 detector 形成 baseline，先移到 GPU 并按全帧运行频率 benchmark。
- 纯 NumPy/OpenCV SEUCM、z-buffer、Hungarian/Kalman、RANSAC/PCA。
- RTX 5060 8GB 足够；CPU 可承担几何部分。

### 延迟/工作量

目标 10–20 Hz 跟踪、3–10 Hz 检测，端到端观测 P95 <250 ms。约 1–2 周开发与离线验证，真实标定另计。

### 风险

box 混入背景、透明/反光深度失败、COCO 类别缺失、遮挡后 ID 不稳。只适合稀疏桌面和保守 top-down。

### 测试与迁移

先完成相机模型/深度注册/追踪/状态机纯函数测试；接口与 B 相同，之后替换 `Detector` 即可。

## 架构 B：增强实例分割与对象记忆（推荐目标）

### 数据流

Lumos 原生/可选多虚拟视图 -> RTMDet-tiny-ins 或经许可的 YOLO-seg -> mask-aware BoT-SORT/Norfair 3D tracker -> base-frame ObjectMemory -> mask 点云/桌面剔除 -> top-K 几何 grasp -> checker/state machine -> Dry Run/人工批准 -> 分层结果验证。

### 算法与资源

- 实例 mask、三维 Mahalanobis 和外观 embedding 联合匹配。
- 对象记忆维护 covariance/TTL/ambiguous state。
- 几何候选为默认；可插拔 GPD/学习式 candidate provider。
- 确定性约束监控借鉴 Code-as-Monitor；事件摘要供 REFLECT/LERa 类离线解释。

### 延迟/工作量

目标检测/分割 5–15 Hz、跟踪/监控 20–30 Hz、P95 <250 ms，显存峰值 <7.2GB。约 3–6 周，包含本机数据标注、训练/微调和回放 benchmark。

### 风险

模型/权重许可、8GB 显存、鱼眼域偏移、mask 漂移、系统复杂度。通过同一回放集和 feature flags 控制；A 始终可回退。

### 测试与迁移

增加 COCO mask metrics、HOTA/IDF1、遮挡重关联、对象记忆误合并和抓取点云纯度。旧 bridge 仅为适配器，不改核心类型。

## 架构 C：研究扩展

### 数据流

B + SAM2 video/开放词汇检测 + FoundationPose/BundleTrack + Contact-GraspNet/GPD + TSDF/多视角对象重建 + 低频 VLM constraint/replanning。

### 算法与资源

支持任意文本目标、持久 mask、已知/未知对象 6D pose、学习式 6-DoF grasp、语义失败诊断。多个大型模型不能默认同时常驻 8GB；需模型调度、TensorRT/ONNX 或第二 GPU。

### 延迟/工作量

P95 可能 0.5–数秒；实时层仍由 B 的 tracker/checker 负责。研究工作量 2–4 个月以上。

### 风险

显存/依赖/许可、域迁移、难以证明安全、VLM 幻觉、标注和 CAD 成本。任何模型输出都不得直接控制机械臂。

### 测试与迁移

每个 provider 作为独立插件，以 B 输出作降级；shadow mode 比较，不替换已验证的 safety evaluator。

## 决策矩阵

| 维度 | A | B | C |
|---|---:|---:|---:|
| 快速可用 | 5 | 3 | 1 |
| 抓取点云纯度 | 2 | 4 | 5 |
| 遮挡/对象记忆 | 2 | 4 | 5 |
| 8GB 可行性 | 5 | 4 | 2 |
| 可解释/可测试 | 5 | 4 | 2 |
| 开放词汇/研究价值 | 1 | 3 | 5 |
| 许可可控性 | 3 | 4（选 RTMDet） | 2 |

结论：以 A 的模块与离线 gate 起步，交付目标为 B；C 仅作为可插拔研究路线。

## 被拒绝方案

- 仅用 homography/固定像素比例完成全工作区定位：只在单平面和局部姿态有效。
- 用 D435 RGB 作为主视觉：违背 Lumos 主 RGB 约束且缩小视场。
- 用 bbox 中心或桌面平面交点直接抓取：不代表对象表面/几何中心。
- 端到端 VLA 直接输出动作：数据、精度、安全和可解释性不满足当前阶段。
- 先上大型 6-DoF grasp 网络再补标定：错误坐标链会使任何模型分数无意义。
