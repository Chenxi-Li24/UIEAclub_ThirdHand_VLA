# VLA Adapter

状态：**仅规划脚手架。**

这里将放置 VLA 模型的加载、输入规范化、推理和输出适配代码。输入应引用带版本的视觉观测与任务文本；输出必须转换为平台候选动作协议，并包含模型版本、置信度和失败原因。

checkpoint 放入 `local/models/policies/vla/`，不得提交 Git。该适配器不得连接 Robot Service 或访问 `can0`。

完成标准见 [`../../../docs/MIGRATION_BACKLOG.md`](../../../docs/MIGRATION_BACKLOG.md)。
