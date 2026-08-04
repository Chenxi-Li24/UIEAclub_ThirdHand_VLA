# REMIND-3D Offline Deployment Results

记录日期：2026-08-04（Asia/Shanghai）
工作区：`/home/nieqingcao/TH-Fanxy`
分支：`codex/vision-safety-core-20260804`

## 当前结论

REMIND-3D 的硬件隔离代码路径、确定性回放、模型适配器、部署配置和独立环境已经建立。
官方 COCO RTMDet-Ins tiny 与 DINOv2-small 已在 RTX 5060 上通过真实 Lumos 图像冒烟测试。
这证明模型运行链路可用，不代表任务专用模型、标定或机械臂闭环已经验收；机械臂执行继续关闭。

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
| 机械臂在线接入/运动 | 禁止 | 本轮仅通过 HTTP 只读采集 Lumos 图像；没有 CAN、Startouch、Robot 或 Gripper I/O |

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
5. 上述项目全部通过前，不接入在线服务、不生成可执行抓取命令、不移动机械臂。
