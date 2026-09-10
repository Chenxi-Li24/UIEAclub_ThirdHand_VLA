# Skill Contract v0.1 提案

## 1. 目标

SkillContract 不是给模型看的自然语言说明书，而是 Planner、Supervisor、Policy Adapter、Verifier 和 Logger 共同遵守的可版本化协议。它必须同时回答：能做什么、何时能做、允许改变什么、什么证据算成功、下一 Skill 是否可接、失败怎样安全退出。

## 2. 顶层字段

| 字段 | 必需 | 含义 |
|---|---:|---|
| `identity` | 是 | `skill_id`、semantic version、owner、status、content hash |
| `description` | 是 | 给模型与人看的能力/非能力边界；含反例 |
| `policy_variants` | 是 | rule/ACT/diffusion/VLA等候选、版本、设备、适用域和优先级 |
| `inputs` | 是 | 严格类型、单位、frame、范围、枚举、freshness、nullable规则 |
| `outputs` | 是 | 返回的事实与artifact，不把期望效果当既成事实 |
| `preconditions` | 是 | 执行前必须成立的世界/机器人/资源/证据谓词 |
| `invariants` | 是 | 执行期间持续成立的安全/任务约束 |
| `expected_effects` | 是 | 执行后预期世界变化，含容差和deadline |
| `handoff_readiness` | 是 | 下一类 Skill 可执行所需的终态谓词 |
| `verification` | 是 | 规则/VLM/多视角证据、PASS/FAIL/UNKNOWN与组合逻辑 |
| `recovery` | 是 | 可恢复失败、候选动作、预算、幂等性/可逆性、禁止项 |
| `safety` | 是 | workspace、速度、负载、碰撞/禁区、approval和stop要求 |
| `resources` | 是 | 机器人、夹爪、相机、GPU/API等互斥/共享锁 |
| `timeouts` | 是 | precheck、execute、verify、total deadline |
| `logging` | 是 | 必录事件、帧、状态、版本和隐私/保留策略 |
| `evaluation` | 是 | 成功、时延、恢复、误触发、成本指标和已知基线 |

## 3. 概念性 Schema 示例

以下是契约表达示例，不是实现代码，也不代表当前系统已具备这些接口：

```yaml
identity:
  skill_id: tabletop.pick
  version: 0.1.0
  status: experimental

inputs:
  object_ref: {type: tracked_object, max_age_ms: 300}
  grasp_pose: {type: pose6d, frame: robot_base, unit_translation: m, unit_rotation: rad}
  lift_height: {type: scalar, unit: m, range: [0.02, 0.15]}

preconditions:
  - robot.mode == READY
  - object_ref.visible == true
  - object_ref.depth_valid == true
  - grasp_pose.inside_workspace == true
  - gripper.empty == true

invariants:
  - tcp.inside_safe_workspace
  - velocity <= configured_limit
  - target_track.not_lost_longer_than_ms: 500

expected_effects:
  - object.attached_or_following_gripper == true
  - object.height_delta >= lift_height - tolerance

handoff_readiness:
  place:
    - object.secure_in_gripper == true
    - target_place_region.visible_or_registered == true
    - robot.has_collision_free_exit == true

verification:
  deterministic_first: true
  outputs: [PASS, FAIL, UNKNOWN]
  vlm_trigger: evidence_conflict_or_semantic_ambiguity

recovery:
  ordered: [reobserve, reparameterize_grasp, retry_same_policy, alternate_policy, replan, human_stop]
  retry_budget: 2
  world_change_budget: 3
```

## 4. Preconditions

分四组，不能只写自然语言：

1. **Robot：** mode、急停、夹爪占用、关节/笛卡尔位置、温度/错误码、最近状态时间。
2. **World：** 目标身份、位置/深度有效性、可见性、目标区域、障碍/人手、桌面/容器状态。
3. **Evidence：** 相机/深度新鲜度、标定版本、跟踪置信度、frame conversion有效。
4. **Resources：** robot/gripper/camera锁、模型服务可用性、剩余时间/调用/重试预算。

每个 precondition 结果是 PASS/FAIL/UNKNOWN。UNKNOWN 不得自动当 PASS；可触发补观测或人工确认。

## 5. Inputs / Outputs

- 输入引用对象必须是带时间戳、来源和 tracking identity 的 `object_ref`，不是自由文本名称。
- 所有 pose 必须带 frame 和单位；orientation 明确 Euler convention 或 quaternion，禁止裸 `rpy`。
- 输入参数区分 Planner-proposed 与 Host-derived；安全上限只能 Host 提供。
- 输出只声明调用结果、receipt、测量和 artifact；`command_complete=true` 不得输出 `task_success=true`。
- 错误是枚举与结构化字段：`INVALID_ARGUMENT`、`STALE_OBSERVATION`、`PRECONDITION_FAIL`、`SAFETY_REJECT`、`EXECUTION_TIMEOUT`、`EFFECT_FAIL`、`HANDOFF_NOT_READY`、`VERIFIER_UNKNOWN` 等。

## 6. Invariants

执行期间高频检查，模型不能覆盖：工作空间、速度/加速度、禁区、人手/障碍、通信 watchdog、观测时效、资源所有权。任务不变量可包括“目标未离开允许区域”“已抓物体未丢失”“容器保持直立”等。每个 invariant 指明监测频率、容差、触发后的 stop type 和证据源。

## 7. Expected Effects

效果不是一条 `success=true`，而是可组合谓词：对象从 A 区域消失/随夹爪移动/高度改变/在 B 区稳定；机器人到达允许容差；夹爪状态变化。每个 effect 指明：deadline、允许误差、最小稳定帧数、主/辅证据、遮挡时 UNKNOWN 规则。

## 8. Handoff Readiness

局部 effect 与下一个 Skill 的前置条件分别检查。例如 Pick 已把杯子抬起，但杯口朝向、夹持位置或臂姿使 Pour 不可执行，应记录 `EFFECT_PASS + HANDOFF_FAIL`。readiness 按“下一 Skill 类型”定义，而非一个通用 bool，至少包含：对象状态、机器人退出/进入姿态、可见/可定位性、剩余工作空间、所需工具/资源和安全裕量。

## 9. Verification

每个谓词声明 verifier chain：

1. 硬安全/机器人状态；2. 几何/深度/追踪规则；3. 时间一致性；4. 多视角补证据；5. VLM 语义验证；6. 人工复核。组合输出 PASS/FAIL/UNKNOWN，保留所有 evidence refs。VLM 给出的理由仅作审计，不覆盖硬规则；任何调用超时返回 UNKNOWN。

## 10. Recovery

Recovery entry 至少包含 failure class、动作是否幂等/可逆、前置条件、最大次数、cooldown、world-change budget、升级路径和 forbidden actions。对“可能仍夹着物体”“物体位置未知”等状态，不能盲目重试完整 Pick；先 reobserve/reconcile state。

建议恢复顺序：重观测 → 重参数化 → 同策略重试 → 备用 Policy → 全局 Replan → 人工停止。每次恢复后重新执行 precheck，不继承旧 PASS。

## 11. Safety

- `approval_mode`: dry-run / human-each-action / human-plan / reviewed-autonomy；初期至少 plan + first motion 人工门。
- 固定 workspace、速度/加速度/力（若有）上限、负载与禁区，不能由 plan 修改。
- `capability_token` 仅授权一个已校验动作窗口，过期/完成即失效。
- 必须有 stop/abort receipt；网络/API超时不可导致继续移动。
- Planner、VLM、Memory 均无 SDK credential；RobotExecutor 独占。

## 12. Logging

SkillContract 要求事件序列：`plan_proposed/validated/rejected`、`precheck`、`approval`、`command_started/receipt`、`observation`、`predicate`、`verifier_request/result`、`effect_result`、`handoff_result`、`recovery_decision`、`episode_outcome`。每条带 monotonic time、wall time、episode/step、版本、frame/calibration、evidence path 和 correlation id。

## 13. Policy Variants 与选择

同一 semantic Skill 可有 rule、ACT、diffusion、VLA adapter，但每个 variant 必须声明 observation/action schema、训练/数据版本、已验证任务分布、延迟、设备、失败分布和安全 wrapper。选择器不能只按模型自然语言偏好；至少使用 preconditions、适用域、历史校准成功率、尾延迟、风险与预算。

## 14. 契约验收

一个 Skill 进入 experimental registry 前，至少通过：schema round-trip、错误参数拒绝、frame/unit mismatch拒绝、stale observation拒绝、dry-run trace完整、timeout/abort、effect verifier混淆矩阵、clean/chained handoff测试、恢复预算终止和无SDK越权。进入 reviewed registry 还需 canary 与 holdout，不能因单次成功自动晋升。

## 15. 与已有工作的关系

字段思想来自 OpenETA/RAI/CLASP/BT 等，不应宣称 Schema 本身创新。论文可研究的是：契约中的证据充分性与 handoff readiness 是否能预测真实链式成功、怎样跨异构 policy 校准、以及在预算下如何选择 verifier/recovery。
