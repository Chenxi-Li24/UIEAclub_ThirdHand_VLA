# ThirdHand：站在巨人肩膀上的最终框架

## 一句话结论

不要重新训练一个“万能机器人模型”。把现成视觉模型当作候选证据源，把确定性规则当作安全底座，把大模型限制在语义疑难和失败诊断中，再用有界重规划与 Shadow Executor 闭环。论文创新点放在“效果验证 + 语义交接验证 + 事件触发模型 + 有界恢复”，而不是重复造检测器、机械臂 SDK 或基础模型。

## 在哪块用哪个巨人

| 模块 | 复用对象 | 本框架怎么用 | 绝不让它做什么 |
|---|---|---|---|
| 开放词汇候选 | Grounding DINO | 本地权重、懒加载，只产生候选框和分数 | 单独授权抓取 |
| 稠密视觉特征 | DINOv3 / DINO 系特征 | 接到 Observation Bridge，供跨视角匹配与状态比较 | 直接宣称物体身份已确认 |
| 实时闭集检测 | RTMDet | 作为高频快速候选源，与开放词汇源互补 | 绕过深度、标定和身份门控 |
| 对象记忆 | REMIND 思路 | 维护跨帧身份与状态证据，输出严格事件 | 用历史猜测替代当前证据 |
| 规则监控 | Code-as-Monitor / CLASP 思路 | 前置条件、不变量、效果、交接和任务目标的硬规则 | 被模型覆盖硬失败 |
| 失败反思 | REFLECT / DoReMi / LERa 思路 | 从 trace 诊断失败，只提一次候选重规划 | 无限反思、无限重试 |
| 程序化计划 | ProgPrompt / PlanAR 思路 | 生成结构化剩余计划，再经技能注册表、证据和预算验证 | 生成任意代码或未知技能 |
| 测试与追踪 | RoboHarness 思路 | 严格契约、回放、逐事件 trace、十场景五基线 | 用 demo 成功代替可复现实验 |
| 机械臂接口 | 现有 Startouch bridge 字段 | 只生成内容寻址的 JSON 命令预览 | 导入 SDK、连 CAN、发真实命令 |

## 已经搭好的闭环

```text
现有视觉输出 / JSONL 回放
        ↓
Observation Bridge（严格事件、证据 ID、时间顺序、不可行动默认值）
        ↓
Skill Contract + Registry（精确版本、单位、坐标系、执行器种类）
        ↓
四道门：前置条件 → 动作后效果 → 下一 Skill 交接 → 任务目标
        ↓                       ↑
Hybrid Verifier          诊断 + 最多一次重规划
（硬规则优先，模型仅处理 UNKNOWN）
        ↓
Startouch Shadow Executor（只写预览）
        ↓
必须等待更新后的观测证据，才能继续
```

## 论文创新点怎么写

1. **Evidence-gated Skill advancement**：执行回执不等于任务进展；只有效果和下一技能就绪证据同时通过，状态机才推进。
2. **Semantic handoff verification**：把传统“动作是否完成”扩展为“下一个技能是否真的可接手”，专门解决长链任务中的隐性断点。
3. **Event-triggered hybrid verification**：确定性规则处理可判定事实，仅在语义 `UNKNOWN` 时调用模型；硬失败具有最高优先级。
4. **Bounded diagnosis and replanning**：失败原因受枚举约束，重规划保留已完成前缀、只能选注册技能、最多接受一次，防止循环和越权。
5. **Reproducible safety benchmark**：十类反例、五个基线、独立真值和内容哈希，把“少误推进、少模型调用”变成可复现实验。

## 当前证据（只代表离线回放）

- 10 个场景 × 5 个基线 = 50 次确定性运行。
- `receipt_only`：12 次错误门级推进，FAR 0.500。
- `post_action`：暴露 1 次语义交接错误推进，FAR 0.083。
- `rule_only`、`always_model`、`hybrid`：本矩阵错误推进均为 0。
- `always_model`：20 次模型调用；`hybrid`：5 次，仅在不确定事件触发。
- 配置化成本记账：0.020 对 0.005；这不是在线服务实测费用或延迟。

这些结果支持“在本离线矩阵中减少错误推进和模型调用”的论文主张，不支持真实机械臂成功率、泛化能力或物理安全主张。

## 接下来往里放模块时的顺序

1. 让现有视觉系统只通过 `detection_result`/Observation Bridge 喂证据，不重构现有网页和相机链路。
2. 先接 RTMDet/DINO/REMIND 的只读输出，再在本地具备权重时启用 Grounding DINO 候选适配器。
3. 为每个新 Skill 写 contract、policy card、前置/效果/交接谓词和回放场景。
4. 先跑 `fake`，再跑 `shadow`；真实执行仍须另立审批、硬件急停、限速和现场验收项目。
5. 论文先报告离线消融和失败画廊；真实机器人实验必须单独标注、单独审查，不能和本结果混写。

## 复现实验

```bash
.venv/bin/python scripts/orchestration/run_benchmark.py \
  --manifest configs/orchestration/benchmark_v1.yaml \
  --skills configs/skills/tabletop_pick.yaml configs/skills/tabletop_place.yaml \
  --output-dir artifacts/orchestration-shadow-v1 \
  --baseline receipt_only --baseline rule_only --baseline post_action \
  --baseline always_model --baseline hybrid
```

主要入口：

- 实验表：`artifacts/orchestration-shadow-v1/table.md`
- 全量指标：`artifacts/orchestration-shadow-v1/metrics.json`
- 失败反例：`artifacts/orchestration-shadow-v1/failure-gallery.md`
- 标签规范：`docs/experiments/orchestration-shadow-v1/LABELING.md`
- 局限说明：`docs/experiments/orchestration-shadow-v1/LIMITATIONS.md`

安全不变量：`robot_execution_enabled=false`，`can_execute_world=false`。
