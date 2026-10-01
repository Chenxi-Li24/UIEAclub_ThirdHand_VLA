# Skills

`skills/` 描述由 LLM Controller 或其他编排器发现和调用的高层能力。不是所有 Skill 都已具备执行 Worker；具体状态以各目录说明为准。

| 分类 | Skill | 当前实现状态 |
|---|---|---|
| `vision/inspect-scene` | `vision_inspect_scene` | 已接入 3004 Controller；只读获取现有 3100 原始帧，交由 `deepseek-flash` 描述，不控制相机或机器人 |
| `vision/` 其他目录 | `describe-scene`、`detect-objects`、`supervise-execution` | 协议已定义；基础视觉在线，执行 Worker 不一定可用 |
| `manipulation/bottlegrasp` | 取放适配入口 | `manual-control` profile 在 8766 启动；默认不自行打开相机或机器人，尚非通用自主抓取闭环 |
| `manipulation/` 其他目录 | `pick-and-place` | 协议已定义；自动夹取执行 Worker 待迁移 |
| `policies/` | `vla`、`act`、`diffusion-policy` | manifest 已定义；模型 Worker 待迁移 |

重要边界：Skill 是能力协议，不是直接硬件权限。涉及运动的 Skill 必须生成可审计计划，绑定稳定目标身份，经过用户授权，再由唯一 Robot Service 执行。模型或 LLM 不得直接访问 `can0`。

完整协议见 [`../docs/SKILL_PROTOCOL.md`](../docs/SKILL_PROTOCOL.md)。
