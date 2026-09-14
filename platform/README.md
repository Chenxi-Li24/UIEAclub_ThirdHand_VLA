# Platform

`platform/` 保存跨应用、跨服务共享的稳定协议和发现机制，不放具体硬件驱动或模型推理代码。

| 路径 | 职责 | 状态 |
|---|---|---|
| `contracts/` | TaskPlan、Authorization、TargetRef、SkillResult 等结构 | 基础协议已存在 |
| `skill_registry/` | 读取 Skill manifest，结合服务、设备和模型状态发布可用性 | 基础能力已存在 |

计划中的 `task_engine` 和 `authorization` 尚未实现。当前网页对话产生的候选动作不等于获准执行，LLM 也不能绕过 Robot Service 直接操作硬件。

协议说明见 [`../docs/SKILL_PROTOCOL.md`](../docs/SKILL_PROTOCOL.md)。
