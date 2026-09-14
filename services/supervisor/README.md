# Supervisor Service

状态：**仅规划脚手架，尚未加入 launcher。**

Supervisor 将持续读取视觉状态、稳定目标身份和正在执行的计划，判断目标丢失、深度失效、场景变化或执行偏差。它可以发布警告、请求暂停或中断，但不能直接生成新的机器人运动，也不能发送 CAN 帧。

预期输入来自 Vision Service、Task Engine 和 Robot Service 的只读状态；输出是结构化监督事件。最终由 Task Engine 决定状态转换，由 Robot Service 执行允许的软件停止语义。

迁移任务见 [`../../docs/MIGRATION_BACKLOG.md`](../../docs/MIGRATION_BACKLOG.md)。
