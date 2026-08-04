# REMIND-3D Offline Deployment Results

记录日期：2026-08-04（Asia/Shanghai）
工作区：`/home/nieqingcao/TH-Fanxy`
分支：`codex/vision-safety-core-20260804`

## 当前结论

REMIND-3D 的硬件隔离代码路径、确定性回放、模型适配器、部署配置和独立环境骨架已经建立。
真实 RTMDet 与 DINO 权重推理尚未通过，因此当前状态不能称为“模型部署完成”，更不能接入机械臂执行。

状态分级：

| 项目 | 状态 | 证据 |
|---|---|---|
| 持久实例身份内存 | 已实现、已测试 | 低质量拒绝、遮挡、重入复核、全局备选分配、歧义拒绝、标定和不确定度门禁 |
| 掩码内 D435 三维位姿 | 已实现、已测试 | 腐蚀、稀疏拒绝、MAD 离群过滤、基座变换、保守协方差测试 |
| DINO 掩码描述符适配器 | 代码已实现 | lazy import、patch 覆盖池化、640 px 长边限制；未加载真实权重 |
| RTMDet 实例分割适配器 | 代码已实现 | 严格要求 masks，转换/阈值/标签/形状测试；未加载真实权重 |
| 确定性身份回放 | 已实现、已测试 | 五帧双实例回放，长间隔返回保持 ID，歧义不强制分配 |
| Python 3.11 独立环境 | 骨架已创建 | `/home/nieqingcao/miniconda3/envs/thirdhand-remind3d` |
| Torch/cu128、MMCV、MMDetection | 未安装 | shell 外网不可达 |
| RTMDet+DINO GPU smoke | 未执行 | 依赖与权重缺失 |
| 机械臂在线接入/运动 | 禁止 | 本轮没有相机、CAN、Startouch、Robot 或 Gripper I/O |

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

在线安装命令：

```bash
timeout 180 bash scripts/vision/bootstrap_remind3d_env.sh --install
```

结果：退出码 `124`。Conda 在访问以下地址时反复返回
`Network is unreachable`：

- `https://repo.anaconda.com/pkgs/main/terms.json`
- `https://repo.anaconda.com/pkgs/r/terms.json`
- 对应 channel 的 notices 地址

随后使用本机 Conda 缓存执行：

```bash
CONDA_OFFLINE=true /home/nieqingcao/miniconda3/bin/conda create \
  --name thirdhand-remind3d python=3.11 pip -y
```

该步骤成功，环境为 Python `3.11.15`。当前仅包含：

- `packaging==26.0`
- `pip==26.1.2`
- `setuptools==83.0.0`
- `wheel==0.47.0`

以下真实部署依赖均确认缺失：`torch`、`torchvision`、`transformers`、`mmdet`、`mmcv`、
`onnxruntime`。因此没有运行、也不能声称通过真实 GPU 模型 smoke。

现有 `LumosTouch` 环境仍为 Python `3.10.20`、NumPy `2.2.6`、SciPy `1.15.3`、OpenCV
`5.0.0`；本轮未在该环境安装或升级模型依赖。

## 本地验证证据

```text
195 passed in 0.61s
LAZY_IMPORT_GATE=PASS
```

同时通过 `compileall`、`bash -n`、`git diff --check` 和双次确定性回放。测试范围为
`web-control/server/tests/vision`、`web-control/server/tests/vision_models` 与
`tests/vision_deployment`。

## 恢复步骤

shell 网络恢复后执行：

```bash
bash scripts/vision/bootstrap_remind3d_env.sh --install
```

然后准备 RTMDet 实例分割 config/checkpoint 和一张包含目标物的真实 Lumos RGB 图，执行：

```bash
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python \
  scripts/vision/smoke_remind3d_models.py \
  --config configs/vision/remind3d.yaml \
  --image /absolute/path/to/lumos-smoke.png \
  --detector-config /absolute/path/to/rtmdet-ins-config.py \
  --detector-checkpoint /absolute/path/to/rtmdet-ins-checkpoint.pth \
  --labels cup,bottle \
  --output artifacts/vision/remind3d-smoke.json
```

DINOv2 fallback 可直接使用 `facebook/dinov2-small`。切换 DINOv3 前仍需接受相应许可并配置
Hugging Face 访问权限，凭据不得写入仓库。

## 仍未通过的门禁

1. PyTorch 2.7.0 cu128 必须在 RTX 5060 上报告 `sm_120` 并成功分配 CUDA tensor。
2. 当前依赖只有精确版本 pin，没有可验证的 `--require-hashes` 锁文件；网络恢复并完成解析后，
   必须生成带 wheel 哈希的锁文件，才可称为完全可复现安装。
3. MMCV 2.1.0 与 PyTorch 2.7/cu128 没有现成的本机通过证据；若 CUDA ops 无法编译，
   RTMDet 应改走经过验证的 MMDeploy ONNXRuntime/TensorRT artifact，而不是降低安全检查。
4. RTMDet 必须在真实 Lumos 图上返回非空实例掩码，box-only 结果一律失败。
5. DINO 必须对每个 mask 返回有限、单位范数、维度一致的描述符。
6. 真实回放仍需完成 mask recall、长间隔 ReID、ID switch、绝对位置、静态 jitter、延迟和显存验收。
7. Lumos 内参、D435-to-Lumos 外参和手眼标定仍需重新采集并独立验证。
8. 上述项目全部通过前，不接入在线服务、不生成可执行抓取命令、不移动机械臂。
