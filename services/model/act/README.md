# ACT Adapter

状态：**仅规划脚手架。**

这里将承载 ACT 策略的环境加载、观测预处理、轨迹推理和协议适配。待迁移来源目前保存在 `History/source-snapshots/policy-act`。

checkpoint 放入 `local/models/policies/act/`，不得提交 Git。输出轨迹必须经过 Task Engine、安全策略和一次性授权，不得直接控制机械臂。

完成标准见 [`../../../docs/MIGRATION_BACKLOG.md`](../../../docs/MIGRATION_BACKLOG.md)。
