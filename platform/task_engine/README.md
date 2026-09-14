# Task Engine

状态：**仅规划脚手架。**

Task Engine 将实现任务状态机，负责计划修订、步骤推进、超时、取消、失败和恢复语义。它接收获准的 `TaskPlan`，调用 Skill，并记录每一步的输入、结果和状态变化。

它不包含模型推理、视觉算法或机器人驱动。涉及物理动作时必须先调用 Authorization 校验，并通过 Robot Service 执行；失败时默认关闭后续动作，而不是自行猜测恢复路径。

迁移任务见 [`../../docs/MIGRATION_BACKLOG.md`](../../docs/MIGRATION_BACKLOG.md)。
