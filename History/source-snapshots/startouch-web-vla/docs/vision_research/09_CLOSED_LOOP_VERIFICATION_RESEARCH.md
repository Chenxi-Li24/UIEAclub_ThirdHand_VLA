# 闭环验证与失败恢复研究

## 设计原则

闭环不是“动作结束后再问一次 VLM”。低层确定性检查应高频运行，语义/VLM 检查只在子目标边界或异常诊断时使用。论文 DoReMi、Code-as-Monitor、REFLECT、LERa、PLanAR 和 Semantic Handoff Failure 的共同信息是：执行结果、下一技能就绪状态和约束必须被显式验证；开环技能单独成功不代表技能衔接成功。

## 多层监控

1. **命令层**：request/step id、ack、完成、`reached`、错误码、deadline、断连。
2. **运动层**：关节状态新鲜度、目标误差、速度、奇异性/限位、停止状态。
3. **视觉层**：目标仍是同一 object、可见/稳定/新鲜、抓取过程中相对位置未超门限。
4. **结果层**：夹爪闭合结果、目标是否离桌、目标是否随夹爪移动、放置区中是否出现目标。
5. **语义层**：子目标谓词与约束，例如 `held(object)`、`inside(object, zone)`、`upright(object)`。

低层失败立即安全停止/中止；VLM 只能解释和提出恢复建议，不能绕过安全门禁自动发运动命令。

## 安全状态机

```text
IDLE -> OBSERVING -> CANDIDATE_READY -> AWAITING_APPROVAL
     -> APPROVED -> EXECUTING_STEP -> VERIFYING_STEP
     -> COMPLETED
任意阶段 --error/timeout/stale/disconnect--> ABORTED
ABORTED --explicit reset + new observation--> IDLE
```

每一步有期望事件集合和绝对 deadline。只有 `operation_id`、`step_id`、命令类型、成功状态全部一致才推进。迟到、重复或无关事件写审计日志并忽略。

## 子目标验证

- 抓取前：目标连续稳定、深度覆盖、候选仍有效、相机/机械臂状态新鲜。
- 下探前：重新观测目标相对预抓取误差，超门限则停止并回到候选生成。
- 闭合后：夹爪状态合理；目标 mask/点云与夹爪共同上移；桌面原位置不再出现同一目标。
- 放置后：目标在期望区域且稳定，夹爪已释放，未检测到明显倾倒/掉落。

## 论文启示的工程化

- PROGPROMPT：程序化 precondition/assert/recovery 优于纯自然语言序列；采用类型化谓词和断言。
- DoReMi：持续检查 plan-execution constraint，违例立即中止/重规划。
- Code-as-Monitor：把对象/部件抽象为点、线、面等几何元素，只在子目标开始生成监控逻辑，执行时运行确定性代码。
- REFLECT：保留分层、多模态事件摘要，失败后供人和模型解释；不让摘要丢失低层证据。
- LERa：视觉重规划对未知失败有效，但第一视角遮挡会导致误判；必须保留确定性 checker。
- PLanAR/semantic handoff：不仅验证当前动作表面完成，还验证下一技能的 ready state；强制 handoff predicate。

## 恢复策略

自动允许的恢复仅限无动作的重观测、重推理、候选失效和 UI 提示。任何真实机械臂恢复（重试抓取、撤回、回 home）都需要新的人工批准，直到大量实机验证证明安全。

## 验收

- 状态机属性测试：无事件顺序可越过批准；错误后不会被迟到完成复活；重复消息幂等。
- 故障注入：丢 ack、错误 request id、完成超时、`reached=false`、相机 stale、目标换 ID、网络断开。
- 执行日志可重放，包含所有输入、状态转换、拒绝原因和版本。
