# Orchestrator Application

状态：**Phase 2 已实现语音/文字候选到夹爪的一次性授权闭环。**

本目录将承载 LLM 任务规划和 Skill 调用编排，把网页或语音请求转换为可审计的 `TaskPlan`。它负责选择可用 Skill、组织步骤、展示风险和请求授权，不负责设备驱动或底层运动控制。

预期依赖：

- `platform/contracts`：计划、目标、授权和结果结构；
- `platform/skill_registry`：查询当前可用 Skill；
- `platform/task_engine`：执行任务状态机；
- `platform/authorization`：验证一次性用户授权。

禁止直接访问 `can0`、Startouch SDK、相机原生驱动或模型权重。物理动作只能通过获准计划调用 Robot Service。

迁移任务和启用条件见 [`../../docs/MIGRATION_BACKLOG.md`](../../docs/MIGRATION_BACKLOG.md)。

当前入口为 `src/server.js`，默认仅监听 `127.0.0.1:3200`，浏览器通过 Web Gateway 的 `/plan` 访问。只支持 `gripper.open` 和 `gripper.close`；其余运动意图失效关闭。Orchestrator 不导入 Startouch SDK，实际执行通过带私有令牌的 Robot Service `/execution` 通道完成。
