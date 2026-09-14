# 创新威胁与重合地图

## 1. 结论先行

原设想不能再表述为“首次让 Codex/VLM 选择结构化机器人 Skill，并通过视觉验证、失败重试/重规划和 Memory 完成真实桌面任务”。这句话的每一部分都有强先例：OpenETA覆盖组合后的完整架构边界（但开放真机运动仍为stub），PLanAR则在论文中覆盖完整真实机器人闭环。

## 2. 分层地图

### 完全或近乎完全重合

- **OpenETA/ETA：** Planner、typed Tools/Skills、Host-owned safety/approval、动作后新观测、验证、记忆、回放、仿真/真机统一adapter边界；其开放真机运动控制仍为stub，所以“架构完全重合”不等于“代码已完整控制真机”。
- **PLanAR：** 任务解析、grounding、规划、执行、Action Checker、验证/重规划、多视角真机。
- **Semantic Handoff：** clean vs chained terminal state、next-skill readiness、typed args、预算与多视图 verifier。

### 高度重合

- **CaP-X：** Coding Agent、代码策略、多轮视觉差分、自动 Skill library、跨基准与真机 bring-up。
- **ASPIRE：** trace 诊断、代码修复、验证、成功模式沉淀为技能库。
- **ENPIRE / RHO：** Coding Agent 修改/搜索机器人策略与训练仓库，真实/仿真评测。
- **Code-as-Monitor / DoReMi：** 执行中约束监控、视觉验证和 replan。
- **CLASP：** 结构化 Skill schema、参数、preconditions、选择/绑定/组合。
- **LERa / REFLECT：** 视觉失败解释、replanning、经验摘要与复用。
- **RAI / ROS-LLM：** 类型化工具、机器人 API、ROS 2 Agent、BT/状态机/反思。

### 部分重合或底层工具

- **CaP、ProgPrompt、SayCan、Inner Monologue：** 奠基 LLM API/Skill 选择、Prompt assertions、affordance、闭环反馈。
- **LeRobot、OpenVLA、openpi、Octo、RT、ACT、Diffusion Policy：** 提供 learned policy/Skill，不提供完整 Supervisor；与“异构 Skill”交叉。
- **VoxPoser、ReKep：** 提供空间/关键点约束和闭环动作生成。
- **MoveIt Task Constructor、BehaviorTree.CPP、PlanSys2：** 提供任务/执行结构与恢复语义，不覆盖 LLM/VLM 科研主张。
- **RoboCasa、BEHAVIOR、LIBERO、RLBench、robosuite：** 仿真与基准基础设施。

## 3. 12 个拟议创新点的裁决

| 想法 | 已有工作 | 裁决 |
|---|---|---|
| 1. LLM 根据自然语言调用 Skill | SayCan、CaP、RAI、OpenETA | 已完成；不能作为创新 |
| 2. Prompt 提升 Skill 选择 | ProgPrompt、CaP、ROS-LLM | 已完成；可作为 baseline/工程消融 |
| 3. 结构化输入输出/前后置条件 | CLASP、RAI、OpenETA、行为规划传统 | 已完成；属于必要基础设施 |
| 4. 执行后视觉判断成功 | Inner Monologue、LERa、PLanAR、OpenETA | 已完成；需在 verifier 校准/路由上创新 |
| 5. 执行中持续监控约束 | DoReMi、Code-as-Monitor | 已完成；规则/VLM成本最优路由仍可研究 |
| 6. 失败后 LLM/VLM Replan | Inner Monologue、DoReMi、LERa、PLanAR | 已完成；只能研究触发、预算、可靠性 |
| 7. Skill 成功但下一 Skill 不可执行 | Semantic Handoff | 直接完成；真机低成本扩展可作为空白 |
| 8. 历史/Memory 加速任务 | REFLECT、LRLL、OpenETA、ASPIRE | 已完成；需研究可信晋升/遗忘/适用域 |
| 9. 成功代码自动整理为 Skill | CaP-X、ASPIRE，亦有非机器人Agent先例 | 已完成；不能作为新点 |
| 10. Rule/ACT/DP/VLA 共存 | 多框架可组合、OpenETA有Policy Adapters | 架构能力不新；选择与handoff实证可研究 |
| 11. Coding Agent 自动改策略仓库 | RHO/HELIX、ENPIRE、ASPIRE | 已完成；直接威胁 |
| 12. 真机比较成功率与时间 | 大量机器人论文/ENPIRE/PLanAR | 实验要求，不是创新 |

## 4. 仍相对安全的区域

“安全”不表示无人触及，而是尚未被完整、充分覆盖，且适合 Touch R1 验证：

1. **真实低成本 handoff benchmark：** 固定鱼眼 + 临时/缺失深度、标定漂移、遮挡与链式终态；比较规则、ACT/DP/VLA 等异构 Skill。现有 Semantic Handoff 以仿真为主。
2. **Evidence-gated verifier routing：** 用可校准不确定性在 deterministic monitor、额外观测、多视角和 VLM 之间选最低成本证据，联合优化危险误放行、误中止、时延与调用成本。
3. **有预算、风险敏感恢复：** 不是普通 Retry/Replan，而是把 failure class、动作可逆性、world-change risk、remaining budget 和 next-skill readiness 结合成可评价策略。
4. **真实链式退化测量：** 同一 Skill 在 clean snapshot 高成功但在 chained state 失败的量化曲线、失败传播和可复现 trace 数据。
5. **异构策略契约一致性：** 不宣称“支持多 Policy”，而是测量相同 SkillContract 是否能预测不同 policy 的适用域、终态分布和 handoff 风险。

## 5. 推荐与禁止的论文表述

### 禁止/高风险

- “首次提出 LLM 驱动机器人 Skill 编排闭环。”
- “首次用视觉验证机器人动作并失败重规划。”
- “首次提出结构化 Skill schema / semantic handoff / automatic Skill library。”
- “首次用 Coding Agent 自动改进机器人代码。”
- “支持 rule-based 和 VLA 等多 Skill，因此具有创新性。”

### 可辩护方向（仍需实验）

- “提出面向低成本桌面机械臂链式 Skill 执行的证据门控验证路由，在受限延迟/调用预算下减少危险误放行与不必要中止。”
- “构建真实 Touch R1 handoff benchmark，系统量化 clean-start 与 chained-terminal-state 差距及低成本感知缺陷造成的失败传播。”
- “通过统一契约测量异构策略的适用域、终态可执行性与风险敏感 fallback，而非只测单 Skill 成功率。”

## 6. 向老师汇报时的红线

必须直接说明：原整体架构已经被公开实现；最新威胁不是尚未开放的遥远概念，而是 2026-08-03 仍更新的 OpenETA。若继续按原标题开工，最终很可能只能得到工程复现。需先决定接受“真实系统/基准论文”还是增加形式化 verifier routing/风险敏感恢复方法，使 Contribution 可独立于系统搭建成立。
