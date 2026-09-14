# Robot Skill Orchestration 深度调研：执行摘要

**检索截止：2026-08-06；对象：Touch R1 / ThirdHand；本轮仅调研，不含实施或机械臂操作。**

## 最终判断

会议设想的完整闭环已经有人做过，而且 2026 年出现了与拟议边界几乎同构的系统。尤其是 [OpenETA](https://github.com/OpenMOSS/OpenETA) 已公开“Planner—类型化 Tool/Skill—主机侧审批与安全门—动作后强制新观测—验证—记忆—回放—统一适配”架构；但要严格区分：其真实硬件目录虽有 RealSense/UR5e 观测与驱动骨架，MCP 运动控制工具截至检索日仍明确为 stub，不能宣称已开放完整真机动作闭环。[PLanAR](https://planar-robot.github.io/) 覆盖多视角 RGB-D、技能执行、Action Checker 与重规划；[Diagnosing Semantic Handoff Failures](https://arxiv.org/abs/2607.06256) 直接研究前一 Skill 成功但下一 Skill 不可执行；[CaP-X](https://github.com/capgym/cap-x)、[ASPIRE](https://research.nvidia.com/labs/gear/aspire/)、[ENPIRE](https://research.nvidia.com/labs/gear/enpire/) 和 [RHO](https://arxiv.org/abs/2606.16458) 又分别覆盖代码式策略、自动技能沉淀、真实机器人策略自改进和代码仓库式策略搜索。因此，“LLM 调 Skill + 视觉验证 + 失败重规划 + Memory”整体架构不能再作为论文创新。

最合理的转向是：**以低成本桌面机械臂上的异构 Skill 语义交接为对象，研究证据门控的混合验证与有预算恢复，并发布真实硬件 handoff 基准/轨迹集。** 论文贡献必须是可量化的方法与实验，而不是模块列表。建议比较规则检查、VLM-only、always-VLM、事件触发混合验证，在干净初态与前序 Skill 链式终态上测成功率、误放行、误中止、恢复率、延迟、VLM 调用次数和成本。

## 对 15 个关键问题的直接回答

1. **整体系统是否已做过：是。** OpenETA 最接近公开实现，PLanAR 最接近完整机器人论文闭环；RAI、DoReMi、Code-as-Monitor、LERa 等覆盖主要子问题。
2. **最相似：** OpenETA、PLanAR、Semantic Handoff、CaP-X、ASPIRE、ENPIRE、CLASP、DoReMi、Code-as-Monitor。
3. **最大创新威胁：** OpenETA（系统边界）、Semantic Handoff（交接问题）、PLanAR（全闭环）、ASPIRE/CaP-X（技能生成与积累）、ENPIRE/RHO（Coding Agent 策略优化）。
4. **可直接复用：** 当前 ThirdHand 作为代码母体；OpenETA/CaP-X 作为隔离研究基线；LeRobot 用于数据与 ACT/Diffusion Policy 适配；RAI/OpenETA 的类型化 Tool 与权限边界可借鉴。OpenETA真实运动控制不能直接复用，因为当前仍是stub。
5. **代码母体：** **保留 ThirdHand，不迁移外部母框架。** OpenETA 是最值得下载审计的外部参照，但项目仅公开约两周，不能直接替换现有系统。
6. **看似合适但短期不合适：** openpi、OpenVLA、Octo、RT-1/2、ReKep、BEHAVIOR-1K、OmniGibson、RoboCasa、RLBench、完整 MoveIt/ROS 2 迁移。
7. **研究空白：** 低成本真机、鱼眼/不完整深度、异构策略、链式终态下的 next-skill readiness；以及在安全、调用成本和延迟约束下的校准验证器路由。
8. **Contribution 重定义：** 见 `10_Research_Gap_and_Contributions.md`，推荐 3–4 项“方法 + 数据/基准 + 系统证据”。
9. **架构：** 轻量 Python Supervisor；模型只提议类型化计划，不直接调用 SDK；连续规则监控 + 事件边界 VLM；有界恢复；不可变 Trace。
10. **两周顺序：** 冻结任务/失败分类与 SkillContract → Dry-run/replay 基线 → 记录与故障注入 → 离线标注验证器 → 混合路由消融；真机另设人工安全门。
11. **必须先报老师：** 原整体创新已被覆盖；2026 年直接竞品；新论文故事；Baseline；是否接受系统/基准型论文；真实实验规模与安全边界。
12. **必读：** Semantic Handoff、OpenETA/ETA、PLanAR、CaP-X、ASPIRE、ENPIRE、RHO、Code-as-Monitor、DoReMi、CLASP。
13. **必测代码：** OpenETA、CaP-X、LeRobot、RAI；均先在隔离环境/仿真/replay 中测。HELIX 可测离线仓库搜索。未澄清 License 的 ReKep/LERa 不进入产品代码。
14. **框架选择：** PDDL 暂不采用；借 Behavior Tree 语义但不引入 C++ 框架；CaP-X/OpenETA 作基线；RAI 借 schema/权限；LeRobot 作学习型 Skill 层；MTC 待可靠 URDF/ROS 驱动后再评估。
15. **Touch R1：** 两个月内应自己写轻量 Python Supervisor；完整 ROS 2 Agent 框架的集成成本高于当前收益。

## 复用优先级

| 等级 | 建议 |
|---|---|
| S | 现有 ThirdHand 仓库是唯一母体；不另立外部母框架 |
| A | OpenETA（审计/基线/接口参考）、CaP-X（研究基线）、LeRobot（数据与学习 Skill）、现有视觉与 SDK 适配 |
| B | RAI、REFLECT、BehaviorTree.CPP 语义、Code-as-Monitor 设计、MoveIt Task Constructor（后期） |
| C | PLanAR/DoReMi/CLASP/LERa 等作为论文依据或对比；多数未开放可直接真机复用代码 |
| D | 近期部署 openpi/OpenVLA/Octo/RT 系列；把重型仿真或完整 ROS 2 迁移当 MVP |

## 会议校读与决策门

27页会议转写已逐页校读。原文确认老师把 Skill/平台搭建视为工作量，把核心放在结构化先验/Prompt 如何让 Codex “又好又快”地规划和调 Skill，以及视觉何时介入、失败后换 Policy/Replan；并要求先用一种 rule-based Pick-and-Place 跑通。需要纠正的是，老师当时判断“学术界应该没有那么快”，但 2026 年最新证据已使该前提失效。在老师确认新 Contribution、任务集、Baseline、实验预算与安全协议前，不应进入真机实现。
