# Diffusion Policy Adapter

状态：**仅规划脚手架。**

这里将承载 Diffusion Policy 的模型加载、观测窗口管理、轨迹采样和平台协议适配。当前没有完成迁移的正式 Worker。

模型资产放入 `local/models/policies/diffusion_policy/`。采样轨迹只是候选结果，必须通过计划验证、运动安全检查和用户授权后才能交给 Robot Service。

完成标准见 [`../../../docs/MIGRATION_BACKLOG.md`](../../../docs/MIGRATION_BACKLOG.md)。
