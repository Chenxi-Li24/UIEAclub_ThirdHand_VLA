# Active View Skill

状态：**仅规划脚手架，未创建 `manifest.yaml`，不会被 Skill Registry 发现。**

该 Skill 将在当前视角不足以确认目标身份、深度或可抓取姿态时，规划有限的观察动作并重新获取视觉证据。它组合 Vision、Task Engine、Authorization 与 Robot Service，不拥有相机驱动或机器人设备。

启用前必须定义观察动作范围、目标身份连续性、场景版本、超时、撤销条件和用户授权边界。任何观察运动仍属于物理动作，必须由 Robot Service 执行。

迁移任务见 [`../../../docs/MIGRATION_BACKLOG.md`](../../../docs/MIGRATION_BACKLOG.md)。
