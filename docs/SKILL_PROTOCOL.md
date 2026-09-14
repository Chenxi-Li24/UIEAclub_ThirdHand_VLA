# ThirdHand Skill 调用协议

状态：Foundation v0.2；夹爪授权执行已通过隔离模拟
适用分支：`refactor/unified-platform-foundation`
机器可读契约：`platform/contracts/schemas/`

本文定义中央 LLM、Skill Registry、Task Engine、Skill worker 与基础服务之间的语义边界。`manipulation.gripper-control` 已具备 Worker，但只在 Robot 私有执行端点、状态和授权同时就绪时可用；其余尚未迁移的 Worker 继续返回不可用。

## 1. 角色边界

| 组件 | 可以做 | 不可以做 |
|---|---|---|
| LLM Orchestrator | 理解用户目标、查询 Registry、调用只读 Skill、请求计划 | 直接发送关节角、夹爪值或 CAN 帧 |
| Skill Registry | 校验并发布 Skill 能力、版本、依赖和可用状态 | 加载 worker、伪造资源就绪 |
| Task Engine | 管理任务状态、计划版本、授权、执行和终止 | 绕过 Schema 或复用失效授权 |
| Skill worker | 按 manifest 实现 `invoke/plan/execute/status/cancel` | 越权访问未声明资源 |
| Robot Service | 独占 Startouch SDK 与 `can0`，执行最终限位检查 | 在连接或健康检查时自动运动 |
| Vision Service | 持续采集 RGB-D、维护检测和稳定目标身份 | 直接批准机械臂运动 |
| Supervisor | 独立判断执行是否安全并请求停止 | 自动恢复被中断任务 |
| Web Gateway | 展示计划、风险、画面、状态并接收用户授权 | 把“软件停止”描述为硬件急停 |

## 2. Skill 目录契约

每个 Skill 目录至少包含：

```text
skills/<group>/<skill>/
|- SKILL.md
|- manifest.yaml
|- schemas/
|  |- input.json
|  |- plan.json        # physical-motion 必需
|  `- result.json
|- src/
`- tests/
```

Foundation 阶段允许只提交 `SKILL.md` 与 `manifest.yaml`。此时 Registry 必须标记 `unavailable`，不得因为文档或 manifest 存在就宣称功能可用。

## 3. Manifest 字段

`manifest.yaml` 必须通过 `thirdhand.skill-manifest.v1`：

| 字段 | 规则 |
|---|---|
| `id` | 全局唯一、稳定，例如 `vision.detect-objects` |
| `version` | SemVer；输入、输出或安全语义变化时升级 |
| `risk` | 只能是 `read-only` 或 `physical-motion` |
| `lifecycle` | `request` 或常驻 `worker` |
| `runtime` | `node` 或 `python` |
| `operations` | `invoke/plan/execute/status/cancel` 的声明子集 |
| `requires` | 必须完整声明 services、devices、models |
| `schemas` | 相对 Skill 目录的 Schema 路径 |
| `entrypoint` | 相对路径；文件缺失时 Skill 不可用 |
| `healthcheck` | worker 支持的只读健康检查操作 |

Registry 只读取 manifest 和资源状态，不在发现阶段导入 SDK、模型或 worker。

## 4. 调用信封

传输协议尚未固定为 HTTP、WebSocket 或本地 IPC；所有实现都必须先遵守以下数据语义：

```json
{
  "schema": "thirdhand.skill-call.v1",
  "taskId": "task-20260910-001",
  "traceId": "trace-7f2c",
  "skillId": "vision.detect-objects",
  "operation": "invoke",
  "requestedAt": "2026-09-10T18:00:00+08:00",
  "input": {}
}
```

要求：

- `taskId` 关联完整任务生命周期。
- `traceId` 贯穿一次调用、日志、计划、授权和结果。
- `skillId` 必须与已发现 manifest 完全匹配。
- `operation` 必须在 manifest 的 `operations` 中。
- `input` 必须通过该 Skill 的 input Schema。
- 未知字段、未知 Schema、未知操作和不可用资源一律失效关闭。

高带宽 RGB、深度、点云、mask 和 tensor 不放入信封，只传 `frameRef`、`maskRef`、`robotStateRef` 等本地引用。

## 5. 只读调用

`risk: read-only` 的 Skill 可以在资源就绪后直接 `invoke`。它仍必须：

1. 校验输入 Schema。
2. 记录 taskId、traceId、Skill 版本和依赖版本。
3. 返回版本化结果。
4. 对过期 frame 或 target 明确失败。
5. 不产生机械臂、夹爪、主动视角或 CAN 运动。

主动视角即使由视觉规划触发，只要会移动机械臂，就属于 `physical-motion`。

## 6. 运动调用与授权

运动 Skill 固定使用以下顺序：

```text
plan -> 展示不可变计划与风险 -> 用户授权 -> execute -> supervise -> result
```

`plan` 必须输出 `thirdhand.task-plan.v1`，包含 `taskId`、`planId`、`revision`、`targetRef`、步骤和非空风险列表。

物理执行授权必须通过 `thirdhand.task-authorization.v2`，并绑定：

- taskId
- planId 与 planRevision
- targetRef
- authorizedOperations
- expiresAt
- canonical `planDigest`

授权在 Task Engine 中原子消费一次。旧 v1 可继续读取，但不能授权当前物理执行。

以下任一变化立即使授权失效：计划修订、目标身份、目标位姿版本、动作范围、关键依赖重启、Supervisor 中断、超时或用户取消。授权失效后必须重新计划并再次由用户授权。

## 7. TargetRef 稳定身份

`thirdhand.target-ref.v1` 由 Vision Service 维护。Skill 只引用，不自行猜测身份。

```json
{
  "schema": "thirdhand.target-ref.v1",
  "targetRef": "target-7",
  "class": "bottle",
  "label": "L1",
  "confidence": 0.94,
  "lastSeenAt": "2026-09-10T18:00:00+08:00",
  "poseRevision": 12,
  "frameRef": "frame-1832"
}
```

目标丢失、遮挡超时、重识别冲突或 `poseRevision` 改变时，依赖旧坐标的运动计划不得执行。

## 8. 结果协议

所有 Skill 最终返回 `thirdhand.skill-result.v1`：

```json
{
  "schema": "thirdhand.skill-result.v1",
  "taskId": "task-20260910-001",
  "traceId": "trace-7f2c",
  "skillId": "manipulation.pick-and-place",
  "status": "interrupted",
  "reason": {
    "code": "target_lost",
    "message": "目标连续多帧不可见",
    "details": {}
  },
  "output": {}
}
```

`status` 只能是 `completed`、`interrupted` 或 `failed`。取消、监督停止和依赖丢失使用 `interrupted`；输入错误、实现异常或不可用资源使用 `failed`。不得把部分执行或超时报告为 `completed`。

建议稳定错误码：

| 错误码 | 含义 |
|---|---|
| `skill_unavailable` | 实现或资源不完整 |
| `schema_invalid` | 输入、计划或结果不符合 Schema |
| `authorization_required` | 运动尚未授权 |
| `authorization_stale` | 授权与当前计划或目标不匹配 |
| `target_lost` | 稳定目标身份已失效 |
| `feedback_stale` | 机器人或视觉反馈过期 |
| `limit_violation` | 关节、速度、夹爪或工作区越界 |
| `supervisor_unavailable` | 独立监督不可用 |
| `operator_cancelled` | 用户取消 |
| `software_stop` | 软件停止链路触发 |
| `internal_error` | 未分类实现错误 |

## 9. 健康与可用状态

基础服务使用 `thirdhand.service-health.v1` 返回 `ready/degraded/unavailable`。Registry 只有在以下条件全部满足时才可发布 Skill 为 ready：

- manifest 和全部 Schema 校验通过；
- entrypoint 存在且版本匹配；
- 所需 services 为 ready；
- 所需 devices 和 models 已登记并验证；
- 对运动 Skill，Robot 与 Supervisor 均为 ready；
- worker 健康检查成功。

`degraded` 不能自动解释为“仍可运动”。运动能力只接受明确的 ready。

## 10. 当前 Skill 清单

| Skill | 风险 | 依赖 | 当前 Foundation 状态 |
|---|---|---|---|
| `vision.describe-scene` | read-only | vision, xvisio | unavailable：worker 未迁移 |
| `vision.detect-objects` | read-only | vision, xvisio | unavailable：worker 未迁移 |
| `vision.supervise-execution` | read-only 配置 | vision, supervisor, xvisio | unavailable：worker 未迁移 |
| `manipulation.pick-and-place` | physical-motion | robot, vision, supervisor, startouch, xvisio | unavailable：worker 未迁移 |
| `manipulation.gripper-control` | physical-motion | robot, startouch | ready 取决于 Worker、私有执行令牌、Robot 新鲜且空闲；隔离模拟已通过 |
| `policy.vla` | physical-motion | 上述服务与 policy.vla | unavailable：worker/权重缺失 |
| `policy.act` | physical-motion | 上述服务与 policy.act | unavailable：worker/checkpoint 缺失 |
| `policy.diffusion-policy` | physical-motion | 上述服务与 policy.dp | unavailable：worker/权重缺失 |

## 11. 监督与停止

Supervisor 与执行 Skill 必须独立运行。以下情况必须撤销授权并停止任务：

- 目标身份或位姿版本失效；
- 机器人反馈跳变、过期或突发全零目标；
- 关节/速度/夹爪/工作区检查失败；
- Vision、Robot 或 Supervisor 由 ready 降级；
- 用户取消或软件停止；
- worker 崩溃、超时或结果 Schema 错误。

停止后不自主恢复，不复用旧计划或授权。网页软件停止不是独立硬件急停；真机测试必须让物理断电或硬件急停保持可触达。

## 12. 新增或迁移 Skill 检查表

1. 创建 `SKILL.md` 并写清触发条件、禁用条件和失败语义。
2. 创建并校验 manifest。
3. 添加 input/result Schema；运动 Skill 还要添加 plan Schema。
4. 先提供 fake/replay 测试，再接入真实服务。
5. 为缺失依赖验证 unavailable，不允许静默降级为假结果。
6. 为 plan/authorization/target revision 编写契约测试。
7. 为 cancel、超时、worker 崩溃和 Supervisor 丢失编写测试。
8. 真机测试前单独生成计划和风险摘要，取得一次性用户授权。
9. 记录实现来源、许可证、模型哈希和硬件验收结果。
10. 只有完成验收后，才从 `implementation_not_migrated` 改为 ready。
