# 算法对应关系

| 模块 | SDK 默认状态 | 说明 |
|---|---|---|
| RTMDet-tiny-ins | 提供适配器，不含权重 | Lumos RGB 上的实例分割；要求模型输出实例掩码，不回退成框检测 |
| DINOv2-small | 提供适配器，不含权重 | 对实例 mask 覆盖的 patch 特征加权池化并 L2 归一化 |
| DINOv3 | 未实现 | 未来可实现同一 `FeatureEncoder` 协议，必须独立测试后再声明支持 |
| REMIND 风格身份记忆 | 已实现工程子集 | 类别门控、余弦外观、可选三维位置、Hungarian 全局匹配、双原型库和生命周期 |
| 双相机注册 | 已实现 | D435 针孔反投影、SE(3) 外参、Lumos SEUCM 投影和最近深度选择 |
| 三维位姿 | 已实现 | 掩码腐蚀、最少点数、中位数、MAD 去异常、协方差和噪声下限 |
| 三维跟踪 | 已实现 | 常速度预测、类别门控、协方差加权 Mahalanobis 代价和全局匹配 |
| 主动视角 | 仅建议 | 评估 D435 中央覆盖和深度稳定性，选择已验证观察位或给出有界精调量 |

## 默认数据流

```text
caller RGB
  -> RTMDet masks
  -> DINOv2 descriptors
  -> persistent identity
  -> optional D435 depth registration
  -> optional robust 3D pose
  -> optional multimodal enrichment/selection
  -> immutable PerceptionResult
```

## 论文与实现边界

RTMDet 使用 MMDetection 标准适配方式。DINO 特征默认实际实现为 DINOv2-small。REMIND 模块借鉴感知—关联—更新、全局匹配、work/stable 记忆和身份生命周期，但未实现论文全部上下文、部件与背景通道，因此只能称为 REMIND 风格工程子集。

