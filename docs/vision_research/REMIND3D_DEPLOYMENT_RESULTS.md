# REMIND-3D Offline and Online Deployment Results

记录日期：2026-08-04 至 2026-08-05（Asia/Shanghai）
工作区：`/home/nieqingcao/TH-Fanxy`
分支：`codex/vision-safety-core-20260804`

## 当前结论

REMIND-3D 的硬件隔离代码路径、确定性回放、模型适配器、部署配置和独立环境已经建立。
官方 COCO RTMDet-Ins tiny 与 DINOv2-small 已接入真实 Lumos 与 D435，并作为持续在线服务运行。
这证明双相机采集、GPU 模型、只读状态与恢复链路可用，不代表任务专用模型、跨相机标定、
手眼标定或机械臂闭环已经验收；机械臂执行继续关闭。

状态分级：

| 项目 | 状态 | 证据 |
|---|---|---|
| 持久实例身份内存 | 已实现、已测试 | 低质量拒绝、遮挡、重入复核、全局备选分配、歧义拒绝、标定和不确定度门禁 |
| 掩码内 D435 三维位姿 | 已实现、已测试 | 腐蚀、稀疏拒绝、MAD 离群过滤、基座变换、保守协方差测试 |
| DINO 掩码描述符适配器 | GPU 冒烟通过 | DINOv2-small 对 6 个真实实例掩码输出 384 维单位向量 |
| RTMDet 实例分割适配器 | GPU 冒烟通过 | 官方 COCO RTMDet-Ins tiny 在 Lumos 实帧输出非空实例掩码 |
| 确定性身份回放 | 已实现、已测试 | 五帧双实例回放，长间隔返回保持 ID，歧义不强制分配 |
| Python 3.11 独立环境 | 已部署 | `/home/nieqingcao/miniconda3/envs/thirdhand-remind3d` |
| Torch/cu128、MMCV、MMDetection | 已安装、门禁通过 | Torch 2.7.0+cu128、MMCV CUDA NMS、`sm_120` 实测通过 |
| RTMDet+DINO GPU smoke | 已通过 | 6 个实例、p95 48.9 ms、峰值显存 0.469 GiB |
| 双相机在线 Dry Run | 已部署、30 分钟验收通过 | 1801 个样本零错误，两路序号持续增长，执行始终关闭 |
| 局域网只读页面 | 已部署 | `http://192.168.58.68:3100/camera-test.html` |
| 机械臂在线接入/运动 | 禁止 | 本轮仅通过 HTTP 只读采集 Lumos 图像；没有 CAN、Startouch、Robot 或 Gripper I/O |

## 2026-08-05 双相机在线部署结果

已按确认的逻辑角色部署：

| 逻辑角色 | 当前设备 | 在线行为 |
|---|---|---|
| `canonical_rgb` | Lumos/XVisio 鱼眼 RGB | 唯一主视觉；RTMDet 实例分割、DINO 描述符、身份和叠加画面 |
| `metric_depth` | Intel RealSense D435 Depth | 实时米制深度、时间配对和健康检查 |
| `debug_rgb` | Intel RealSense D435 RGB | 只用于调试画面，不决定目标身份 |

未来换成带深度的鱼眼时，上层仍使用 `canonical_rgb` 与 `metric_depth` 两个角色，只替换
设备适配器和标定配置；检测、身份、目标状态和 fail-closed 门禁无需重写。

### 实机与服务状态

- USB 设备：XVisio `040e:f408`；D435 `8086:0b07`，SDK 序列号 `349622074226`，
  固件 `5.17.3.10`，USB 3.2。
- UVC 重新枚举后，D435 使用 `/dev/video0` 至 `/dev/video5`，Lumos 使用
  `/dev/video6` 与 `/dev/video7`；Lumos 服务按 XVisio 产品名和接口 index 0 自动发现采集节点，
  不再依赖 `/dev/videoN` 的枚举顺序。
- `thirdhand-lumos-online.service` 提供 3001 端口时间戳快照和 MJPEG；
  `thirdhand-dual-camera-online.service` 提供 3100 端口在线模型、状态和双画面。
- 当前入口：Ubuntu 本机 `http://127.0.0.1:3100/camera-test.html`；局域网/Windows
  `http://192.168.58.68:3100/camera-test.html`。
- 新服务固定为 `STARTOUCH_SIMULATE=1`、占位 CAN 接口 `thirdhand-vision-test`、
  `STARTOUCH_GRIPPER=0` 和 `robot_execution_enabled:false`。原 3000 服务 PID `2761127`
  在部署、UVC 恢复和验收期间始终未被停止或替换。
- D435 启动前执行真实 640x480@30 RGB-D 预检；运行时遇到 USB/UVC 瞬态失败会退避重连。
  MJPEG 浏览器断开后会恢复排空，D435 与 Lumos 输出使用独立锁，避免调试流阻塞模型事件。

### 30 分钟真实硬件 Dry Run

端口 3100 的在线服务连续采样 1800 秒，结果为：

```text
passed=true
sample_count=1801
errors=0
fetch_errors=0
stale_samples=0
robot_execution_enabled_samples=0
lumos_sequence_advancement=26967
d435_sequence_advancement=53961
latency_p95_max_ms=71.335
latency_p95_final_ms=56.378
gpu_memory_reserved_max_gib=0.449
source_age_max_ms=81
systemd_restarts=0
```

报告位于 `artifacts/vision/dual-camera-online/readiness-20260805.json`，SHA-256 为
`c3ef895c40c023e45c882b35f1bb03729da2d61dc6bcf0aa512fbb6f74ea4827`。
Lumos 实时叠加抽帧位于
`artifacts/vision/dual-camera-online/lumos-overlay-20260805.jpg`，可见检测框以及
`MODEL READY | EXECUTION LOCKED`。

30 分钟验收后只将监听地址从 loopback 改为 `0.0.0.0`，模型与相机代码未变；随后通过
局域网地址再采样 60 秒，61 个样本零错误，Lumos/D435 序号分别前进 899/1799 帧。
局域网报告位于 `artifacts/vision/dual-camera-online/readiness-lan-20260805.json`。

### 当前安全边界

D435 RGB-D 已在线、深度帧持续前进，但当前 D435-to-Lumos 外参和手眼标定没有独立验收，
因此在线融合器故意传入 `calibration=None`：页面可以显示检测与深度健康，不能输出可信的
机器人基座三维坐标，所有目标均为 `actionable:false`。当前预期阻断项包括：
`calibration_unavailable`、`robot_pose_unavailable`、`arm_not_stationary`、
`observation_below_memory_quality`、`identity_not_actionable` 和
`task_checkpoint_unvalidated`。这些是正确的 fail-closed 证据，不是可绕过的运行错误。

## 新增部署面

- `web-control/server/vision/identity.py`：REMIND 风格 work/stable 多原型身份内存，类别门控、
  短时三维门控、全局 Hungarian 分配、显式 `AMBIGUOUS`。
- `web-control/server/vision/instance_pose.py`：从 D435-to-Lumos 注册点云和实例掩码生成
  `robot_base` 位姿与协方差。
- `web-control/server/vision_models/`：RTMDet、DINO 和回放适配层；仅实例化模型时才导入重依赖。
- `configs/vision/remind3d.yaml`：模型、身份、三维位姿、显存、延迟和 fail-closed 配置；
  `robot_execution_enabled: false`。
- `scripts/vision/bootstrap_remind3d_env.sh`：只创建 `thirdhand-remind3d`，固定 Python 3.11、
  PyTorch 2.7.0、torchvision 0.22.0 和官方 cu128 index。
- `scripts/vision/smoke_remind3d_models.py`：只有 RTMDet 返回真实 mask、DINO 返回有限单位向量、
  GPU 架构受支持、p95 延迟不超过 300 ms，且 allocated/reserved 峰值显存均不超过
  7.2 GiB 时才输出 `smoke_passed: true`。

## 安全复审修正

两轮独立代码复审后已完成以下修正，主要提交为 `1a29b9f` 与 `b5d2879`：

1. 低置信度或低可见度观测不能创建 ID、增加确认次数、更新原型，或锁定特征维度与标定 ID；
   低质量重复框也不能干扰同帧可信观测的分配。
2. 缺失深度只清除当前可操作位姿，保留最近有效三维关联位姿，不能绕过短时位移门禁。
3. 首次获得深度、三维关联超时或 `INACTIVE` 重入后，均需连续两帧高质量 RGB-D 观测；
   重入首帧保持 `TENTATIVE`，任何阶段都不允许首次深度直接解锁。
4. 身份层可操作状态要求标定已验证、标定 ID 匹配、位姿新鲜且位置标准差不超限；
   工作空间、可达性和点云数量仍由已有 `vision.safety` 末级门禁负责。
5. 歧义检测比较完整 Hungarian 分配与禁用已选边后的近优完整分配，并在剔除歧义列后
   迭代到固定点，不再使用局部行列差值或强制分配缩减矩阵中的新歧义。
6. RTMDet 启动时要求配置标签与 checkpoint 的 `dataset_meta.classes` 顺序完全一致。
7. 回放限制 manifest、NPZ、解压体积、压缩比、帧数、观测数和描述符维度，并在
   `np.load` 前预检 NPY header 的 dtype、shape 与实际 payload 字节一致性。
8. 模型 smoke 强制使用一个明确 CUDA 设备完成模型、同步、架构、延迟和显存测量；
   环境脚本固定打包工具版本，前后验证 Python 3.11，并实际执行 CUDA MMCV NMS 门禁。
9. 非空观测帧时间戳必须严格递增，延迟到达的旧帧不能倒退 `last_seen_ns`。

## 确定性回放证据

回放包含两个同类杯子、短时漏检、长期离开后返回、位置移动和一个外观等距的故意歧义观测。

结果：

| 指标 | 结果 |
|---|---:|
| frames | 5 |
| observations | 5 |
| assigned | 4 |
| new identities | 2 |
| known identity transitions | 2 |
| ID switches | 0 |
| ambiguous observations | 1 |
| forced ambiguous assignments | 0 |

两次 CLI 输出经 `cmp` 字节一致。报告 SHA-256：
`6bc7b41d81b1c526668dea57c5556aa95ad395cbf3509a997e385039dbec5da8`。

长期重入帧现在保持原 ID，但状态为 `tentative`，这正是哈希相较首次实现变化的原因。

这只证明身份状态机、关联和指标代码的确定性，不代表真实 Lumos 图像上的 ReID 准确率。

## 环境安装证据

网络恢复后执行：

```bash
bash scripts/vision/bootstrap_remind3d_env.sh --install
```

本机没有适配 PyTorch 2.7/cu128 的预编译 MMCV wheel，因此脚本使用 `/usr/local/cuda`
从源码为 `sm_120` 编译 MMCV 2.1.0 CUDA 算子。构建完成后以下硬门均通过：

```text
TORCH_VERSION_GATE=PASS
IMPORT_GATE=PASS
TORCH=2.7.0+cu128
CUDA_BUILD=12.8
GPU_GATE=PASS
GPU=NVIDIA GeForce RTX 5060
CAPABILITY=(12, 0)
MMCV_OP_GATE=PASS
PYTHON_POST_GATE=PASS
```

关键版本为 torchvision `0.22.0+cu128`、MMEngine `0.10.7`、MMDetection `3.3.0`、
MMDeploy `1.3.1`、Transformers `4.56.2` 和 ONNX Runtime GPU `1.22.0`。
现有 `LumosTouch` 环境没有安装或升级这些模型依赖。

## 真实 Lumos GPU 冒烟证据

Lumos HTTP 服务健康检查报告 `/dev/video0`、原始分辨率 `1920x1280`、目标 `15 FPS`、
`ready: true` 且无采集错误。从实时 MJPEG 流取得一张 480x480 鱼眼帧，SHA-256 为
`3506630bab90f432b088510e7f1f9469cf67a83326ad996cb513d8af1b63e153`。

官方 COCO RTMDet-Ins tiny checkpoint SHA-256 为
`ec670f7ee9e20bd7931e15f15b7016f7fe531baaab81f2e6153382d046111885`。
在阈值 0.35 下，真实帧输出 6 个实例掩码；其中桌面水瓶标签为 `bottle`、置信度
`0.7239`、掩码面积 1844 px。DINOv2-small 为每个掩码生成一个 384 维描述符，范数范围
为 `[0.9999999999999999, 1.0]`。

```text
smoke_passed=true
detection_count=6
descriptor_count=6
latency_p50_ms=44.724
latency_p95_ms=48.893
gpu_peak_allocated_gib=0.370
gpu_peak_reserved_gib=0.469
robot_execution_enabled=false
```

报告位于 `artifacts/vision/remind3d-live-smoke.json`，检测可视化位于
`artifacts/vision/rtmdet-live-smoke.jpg`；两者为 gitignored 运行产物。

## 本地验证证据

```text
196 passed in 0.68s
LAZY_IMPORT_GATE=PASS
```

同时通过 `compileall`、`bash -n`、`git diff --check` 和双次确定性回放。测试范围为
`web-control/server/tests/vision`、`web-control/server/tests/vision_models` 与
`tests/vision_deployment`。

## 复现命令

以下命令复现本次官方 COCO checkpoint 冒烟；完整有序标签直接读取 MMDetection 的 COCO
元数据，不能缩减为 `cup,bottle`：

```bash
PY=/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python
MMDET_ROOT=$("$PY" -c 'import mmdet; from pathlib import Path; print(Path(mmdet.__file__).parent)')
CFG="$MMDET_ROOT/.mim/configs/rtmdet/rtmdet-ins_tiny_8xb32-300e_coco.py"
CKPT=models/vision/rtmdet/rtmdet-ins_tiny_8xb32-300e_coco_20221130_151727-ec670f7e.pth
LABELS=$("$PY" -c "from mmdet.datasets import CocoDataset; print(','.join(CocoDataset.METAINFO['classes']))")

PYTHONPATH="$PWD/web-control/server" "$PY" \
  scripts/vision/smoke_remind3d_models.py \
  --config configs/vision/remind3d.yaml \
  --image artifacts/vision/lumos-live-smoke.jpg \
  --detector-config "$CFG" \
  --detector-checkpoint "$CKPT" \
  --labels "$LABELS" \
  --descriptor-model facebook/dinov2-small \
  --device cuda:0 \
  --min-score 0.35 \
  --iterations 3 \
  --output artifacts/vision/remind3d-smoke.json
```

DINOv2 fallback 可直接使用 `facebook/dinov2-small`。切换 DINOv3 前仍需接受相应许可并配置
Hugging Face 访问权限，凭据不得写入仓库。

## 仍未通过的门禁

1. 当前依赖只有精确版本 pin，没有可验证的 `--require-hashes` 锁文件；仍需生成带 wheel
   哈希的锁文件，才可称为完全可复现安装。
2. 本次使用官方 COCO checkpoint 验证基础设施；仍需针对任务目标物采集、标注、训练并冻结
   专用 RTMDet-Ins checkpoint，随后完成 mask recall 与误检验收。
3. 真实序列仍需完成遮挡、长间隔 ReID、同类实例混淆、ID switch 与静态 jitter 验收；
   单帧冒烟不能证明持续身份准确率。
4. Lumos 内参、D435-to-Lumos 外参和手眼标定仍需重新采集并独立验证，随后验收绝对三维位置。
5. 上述项目全部通过前，在线服务只发布不可操作的 Dry Run 结果，不生成可执行抓取命令，
   不移动机械臂。

## 2026-08-06 主动视角 Dry Run 记录

已将“Lumos 广角发现目标 → 选择 D435 观察位姿 → 深度质量门控 → 有界微调建议”
实现为独立可组合模块。几何估计、位姿规划、身份绑定状态机、在线适配、状态展示和回放验证
之间仅通过不可变数据契约衔接，没有机械臂 I/O 依赖。默认配置中机器人执行和主动视角执行
均为 `false`，桌面模型为未验证，观察位姿目录为空，因此当前不可生成任何真机动作。

离线确定性回放使用 5 帧，覆盖左右两个同类实例、视野未覆盖拒绝、D435 深度合格以及
20 mm 微调限幅：

```text
frame_count=5
proposal_count=3
pose_selection_accuracy=1.0
depth_quality_acceptance_rate=0.5
identity_switches=0
execution_proposals=0
rejection_reasons={depth_quality_sufficient: 1, target_not_covered: 1}
```

回放产物位于 `artifacts/vision/active-view-dry-run/offline-replay-20260806.json`，SHA-256 为
`bf80c135019a4b36ca145f19c6abe016d0adf0da45b79ba835cc5e794c445d1e`。

在不重启、不重配置现有 3100 端口服务的前提下，完成了 60 秒只读实时采样。61 个采样中
Lumos 序列增加 899、D435 序列增加 1799，机器人执行启用样本数为 0。本次就绪性检查
不通过：当前运行的旧进程尚未暴露新增的 `activeView` 状态，所有样本均因
`active-view status is missing` 被拒绝。这是部署版本阻塞，不是抓取就绪证据，也没有为消除
该阻塞而重启现场服务。

实时采样产物位于 `artifacts/vision/active-view-dry-run/readiness-20260806.json`，SHA-256 为
`611bf542bea300008633c7e9b80bf952b47648dbbc67dad9fab7e1ac156be766`。两个产物均为 gitignored 运行证据。

进入任何真机观察移动前，仍必须依次完成桌面模型、Lumos 内参、D435 外参/手眼标定和
受限观察位姿目录的独立验收；第一次发送机械臂观察动作仍需人工拍板。

## 2026-08-06 主动视角控制模拟与故障注入

新增独立纯事件验证器 `scripts/vision/verify_active_view_control.py`。验证器不导入 Startouch、
CAN、相机或网页模块，只评估不可变事件证据；默认 `real_motion_allowed=False`。在线启动脚本
同时显式固定 `ACTIVE_VIEW_EXECUTION_ENABLED=0`，避免继承宿主环境中残留的开启变量。

验证器要求：

- 会话、提议、请求和身份 ID 全程精确关联；
- 证据哈希在会话内不变，提议未过期；
- 每次移动后至少两次同一身份确认；
- 最终至少五个新鲜深度样本，中心最大偏差不超过 10 mm、每轴 MAD 不超过 5 mm；
- 精调平移不超过 20 mm、旋转不超过 5°，且没有沿 D435 光轴的位移；
- 模拟证据中机器人执行与主动视角执行门均为 `false`；
- 不产生抓取命令，故障终止后不再出现后续命令。

故障注入覆盖身份切换、身份歧义、陈旧深度、错误 request ID、提议过期、运动超时、机器人
断连、D435 断连、审批过期、证据变化/失效，以及故障后追加运动或抓取命令。所有故障均被
判为失败，且“正确终止”的故障样本 `commands_after_abort=0`。

虚拟 30 分钟浸泡在不等待墙钟时间、不访问 `--base-url` 的 `--simulation-only` 模式完成：

```text
passed=true
virtual_duration_seconds=1800
session_count=60
completed_sessions=60
observation_moves=120
identity_confirmations=240
depth_samples=360
max_translation_m=0.015
max_rotation_rad=0.0
execution_gate_samples=60
execution_gate_violations=0
identity_changes=0
stale_accepted_proposals=0
unexpected_transitions=0
commands_after_abort=0
grasp_commands=0
```

报告位于 `artifacts/vision/active-view-control/simulation-soak-20260806.json`，SHA-256 为
`6f772fbfd22a1885b33fea9bcae265644c5bc53a166db5f986d5cdface99596a`。该文件是 gitignored
运行证据。

这只证明控制协议、相关性、边界和故障终止在确定性虚拟事件上成立，不证明真实路径无碰撞，
也不证明标定、观察位或真机控制已通过。未连接、未重启现有在线服务，未发送任何机械臂或夹爪
命令；真实观察运动仍停在人工安全确认门之前。
