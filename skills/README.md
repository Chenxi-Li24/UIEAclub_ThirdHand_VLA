# Skills

`skills/` 描述可由未来编排器发现和调用的高层能力。每个 Skill 目录至少包含 `manifest.yaml` 和 `SKILL.md`。

| 分类 | Skill | 当前实现状态 |
|---|---|---|
| `vision/` | `describe-scene`、`detect-objects`、`supervise-execution` | 协议已定义；基础视觉在线；部分 Worker 待迁移 |
| `manipulation/` | `pick-and-place` | 协议已定义；自动夹取执行 Worker 待迁移 |
| `policies/` | `vla`、`act`、`diffusion-policy` | manifest 已定义；模型 Worker 待迁移 |

重要边界：Skill 是能力协议，不是直接硬件权限。涉及运动的 Skill 必须生成可审计计划，绑定稳定目标身份，经过用户授权，再由唯一 Robot Service 执行。模型或 LLM 不得直接访问 `can0`。

完整协议见 [`../docs/SKILL_PROTOCOL.md`](../docs/SKILL_PROTOCOL.md)。
