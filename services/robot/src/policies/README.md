# Robot Policies

状态：**仅规划脚手架；现有 `../motion-policy.js` 仍是当前正式运动策略。**

本目录将用于拆分与 Startouch 机器人直接相关的纯策略，例如关节限位、速度与时间约束、工作空间、回零条件、反馈新鲜度和意外全零目标保护。

迁移时应保持策略为可离线测试的纯逻辑，由 `robot-controller.js` 统一调用。策略不得自行创建 SDK、发送 CAN 帧或绕过命令互斥。现有策略在等价测试通过前不得删除或切换。

迁移任务见 [`../../../../docs/MIGRATION_BACKLOG.md`](../../../../docs/MIGRATION_BACKLOG.md)。
