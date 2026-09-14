# API 说明

## 统一入口

```python
result = pipeline.process(frame_bundle, context={"query": "blue bottle"})
```

`VisionPipeline` 的构造参数为：实例分割器、特征编码器、`PersistentIdentityMemory`、`VisionConfig`，以及可选 enrichers 和 selector。流水线不读取模型路径、不打开设备，也不启动线程。

## 输入

`FrameBundle`：

- `rgb`：`uint8[H,W,3]` RGB；
- `stamp`：来源、帧号和单调时间戳；
- `depth_m`：可选、浮点二维米制轴向深度，无效值为 `NaN`；
- `depth_stamp`：有深度时的时间戳；
- `calibration`：可选 `FusionCalibration`；
- `metadata`：调用方只读元数据。

`FusionCalibration` 包含 D435 针孔模型、Lumos SEUCM 模型、`T_lumos_from_d435`、`T_output_from_lumos` 和带验证状态的标定引用。

## 输出

`PerceptionResult` 包含：

- 每个 `PerceptionInstance` 的 detection、归一化 descriptor、identity、可选 pose、原因码和扩展标注；
- 帧级 blockers；
- 被隔离的扩展错误；
- 可选 `selected_identity_id`。

`to_dict()` 默认不内嵌像素掩码和特征向量，避免 JSON 体积失控；调用方可以直接访问 Python 对象中的只读数组。

## 扩展协议

`FeatureEncoder` 返回每个掩码一个归一化向量。`ResultEnricher` 返回 `{detection_id: annotations}`。`TargetSelector` 返回 `TargetSelection(identity_id, score, explanation)` 或 `None`。

`extensions.mode: strict` 会把扩展异常包装为 `ExtensionError`；`isolate` 保留核心视觉结果，只记录插件名和异常类型。

## 异常

- `InputValidationError`：调用方输入或配置不满足合同；
- `ModelLoadError`：可选依赖或显式模型文件不可用；
- `ModelContractError`：模型输出形状、标签或数量不满足合同；
- `ExtensionError`：协作者扩展在指定阶段失败。

