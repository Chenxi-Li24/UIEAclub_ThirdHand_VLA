# ThirdHand Vision SDK

这是从 ThirdHand 项目独立整理出的离线视觉算法 SDK，供协作者在现有视觉证据上接入 VLM、文本、语音或其他多模态模块。它不连接相机、机械臂、夹爪、CAN、网页或网络服务。

## 当前能力

- RTMDet 实例分割适配器：类别、置信度、框和原生像素掩码；
- DINOv2-small 特征适配器：实例掩码覆盖加权的归一化描述子；
- REMIND 风格身份记忆：类别门控、全局匹配、双特征库、歧义拒绝和遮挡重捕获；
- D435 针孔深度到 Lumos SEUCM 图像的跨相机注册；
- 掩码腐蚀、中位数/MAD 去异常、三维中心和协方差估计；
- 只输出建议的主动视角质量评估和观察位选择；
- `ResultEnricher` 与 `TargetSelector` 多模态扩展接口。

当前默认描述子是 `facebook/dinov2-small`。DINOv3 只作为未来可替换的 `FeatureEncoder`，本包没有把它写成已部署能力。身份模块是 REMIND 方法的工程化子集，不是论文的完整复现。

## 五分钟开始

Python 要求 3.10 或更高版本。

```bash
python -m pip install -e .
python examples/minimal_mock.py
python examples/multimodal_extension.py
python -m pytest -q
```

两个示例不需要网络、GPU、模型权重或硬件。`minimal_mock.py` 展示统一流水线，`multimodal_extension.py` 展示队友应当接入的位置。

## 使用真实模型

模型适配器是可选能力。请先按目标 CUDA/PyTorch 版本安装兼容的 MMEngine、MMCV、MMDetection、Torch 和 Transformers，再安装本包：

```bash
python -m pip install -e '.[models]'
```

`RTMDetSegmenter` 只接受显式本地配置和 checkpoint 文件。`DinoV2Encoder` 默认 `local_files_only=True`，不会隐式下载权重。模型文件不包含在交付 ZIP 中。

## 多模态接入

队友通常不需要修改检测、几何或身份代码：

1. 实现 `ResultEnricher.enrich(frame, result, context)`，给已有 detection 增加附加标注；
2. 实现 `TargetSelector.select(result, context)`，从已有 identity 中选择目标；
3. 如果需要更换视觉表征，实现 `FeatureEncoder.encode(image_rgb, masks)`。

扩展器不能创造不存在的视觉实例，选择器不能返回结果中不存在的 identity。详见 [API](docs/API.md) 和 [迁移指南](docs/MIGRATION.md)。

### 在 ThirdHand 主仓库中复用

主仓库通过 `web-control/server/vision_sdk_adapter.py` 将 SDK 结果转为现有的只读浏览器合约，
通过 `scripts/vision/run_sdk_replay_parity.py` 对旧实现与 SDK 实现做离线逐帧对比。适配器会始终
把 `actionable` 和抓取许可保持为假；一致性报告通过也不会改变这一边界。

```bash
python -m pip install --no-deps -e packages/thirdhand-vision-sdk
PYTHONPATH=packages/thirdhand-vision-sdk/src:web-control/server \
  python -m pytest tests/vision_deployment/test_vision_sdk_adapter.py -q
```

图像语言目标选择属于 SDK 之上的应用层：应用只能从当前 `PipelineResult` 中已确认的
identity 列表中返回一个 ID，不能返回坐标、关节角、夹爪开度或运动命令。语义分数只能用于
离线标定、对比和消融实验，不能作为安全置信度或抓取授权。

## 二维与三维降级

- 只有 RGB：返回检测、特征和身份，附带 `depth_unavailable`；
- 有深度但无标定：返回二维结果，附带 `calibration_unavailable`；
- 标定未验证：不产生可信三维位姿；
- 掩码内有效深度不足：该实例没有位姿，并报告 `insufficient_mask_depth`。

SDK 不使用包围框中心深度伪造三维位置，也不包含任何运动或抓取接口。

## 目录

```text
src/thirdhand_vision/  Python 包
configs/               无机器绝对路径的示例配置
examples/              离线调用与扩展示例
tests/                 无硬件测试
docs/                  API、算法和迁移说明
SOURCE_MAP.json        原始实现到 SDK 的路径与 SHA-256
```

## 完整性

收到 ZIP 后可运行：

```bash
sha256sum -c thirdhand-vision-sdk-20260806.zip.sha256
sha256sum -c MANIFEST.sha256
```

许可和模型分发注意事项见 [LICENSES.md](LICENSES.md)。
SDK 自有代码采用 [MIT License](LICENSE)；模型权重和第三方依赖仍分别遵循其上游许可。
