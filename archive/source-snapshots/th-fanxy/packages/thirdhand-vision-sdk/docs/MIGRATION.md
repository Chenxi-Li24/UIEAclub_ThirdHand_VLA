# 从原项目迁移到 SDK

## 概念映射

| 原项目概念 | SDK 入口 |
|---|---|
| `vision.camera_models` | `thirdhand_vision.core.camera` |
| `vision.geometry` | `thirdhand_vision.core.transforms` |
| `vision.depth_registration` | `thirdhand_vision.geometry.depth` |
| `vision.instance_pose` | `thirdhand_vision.geometry.pose` |
| `vision_models.rtmdet` | `thirdhand_vision.detection.rtmdet` |
| `vision_models.dino` | `thirdhand_vision.features.dino` |
| `vision.identity` | `thirdhand_vision.identity.memory` |
| `vision.tracking` | `thirdhand_vision.identity.tracker` |
| 在线相机桥编排 | `VisionPipeline.process`，由调用方提供帧 |

## 协作者接入原则

- 不从 SDK 内部读取相机；在外层构造 `FrameBundle`；
- 不修改 `PerceptionResult` 中的视觉证据；通过 `ResultEnricher` 返回附加标注；
- 不用文本模型创造 detection；`TargetSelector` 只能选择已有 identity；
- 更换 DINO 时实现 `FeatureEncoder`，确保每个 mask 恰好一个有限、非零描述子；
- 三维结果必须带经过验证的 `FusionCalibration`，否则只使用二维结果。

`SOURCE_MAP.json` 给出每个迁移算法的原始文件、源 SHA-256 和 SDK 目标路径，便于后续核对差异。

