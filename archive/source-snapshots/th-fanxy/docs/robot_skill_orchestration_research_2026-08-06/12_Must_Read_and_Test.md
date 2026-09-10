# 必读论文与必测代码

> 时间是单人有效工作估计；“测试”均是未来计划。本轮未下载、安装或运行任何第三方项目。

## 1. 必读顺序

| 顺序 | 论文/材料 | 为什么必须完整读 | 预计 |
|---:|---|---|---:|
| 1 | [Semantic Handoff](https://arxiv.org/abs/2607.06256) | 与next-skill readiness直接重合；决定能否继续用handoff作为主词 | 3–4h |
| 2 | [ETA论文](https://arxiv.org/abs/2608.03924) + [OpenETA架构/README](https://github.com/OpenMOSS/OpenETA) | 与完整系统边界最接近，且公开时间最新 | 5–7h |
| 3 | [PLanAR](https://arxiv.org/abs/2602.01662) | action schema、symbolic effect、stepwise verification、真机replan | 4–5h |
| 4 | [CaP-X](https://arxiv.org/abs/2603.22435) | coding-agent操控基准、visual differencing、自动skill synthesis | 5–6h |
| 5 | [Code-as-Monitor](https://arxiv.org/abs/2412.04455) | 执行中确定性监视器与VLM调用替代 | 3–4h |
| 6 | [DoReMi](https://arxiv.org/abs/2307.00329) | natural-language constraints、周期VQA、replan强基线 | 3h |
| 7 | [CLASP](https://arxiv.org/abs/2606.08169) | schema/preconditions/skill selection & composition直接威胁 | 3–4h |
| 8 | [ASPIRE](https://arxiv.org/abs/2607.00272) + 项目限制 | 自动trace诊断、代码修复、skill library与明确局限 | 4–5h |
| 9 | [ENPIRE](https://arxiv.org/abs/2606.19980) | 真机coding-agent改进；理解pass@8、reset/verify前提 | 4–5h |
| 10 | [RHO](https://arxiv.org/abs/2606.16458) | repositories-as-policies与离线/在线分离 | 3–4h |
| 11 | [LERa](https://arxiv.org/abs/2507.05135) + [REFLECT](https://arxiv.org/abs/2306.15724) | checker敏感性、失败解释与experience summary | 5–6h |
| 12 | [Inner Monologue](https://arxiv.org/abs/2207.05608) | 闭环语言反馈的基础工作 | 2–3h |
| 13 | [ProgPrompt](https://arxiv.org/abs/2209.11302)、[SayCan](https://arxiv.org/abs/2204.01691)、[CaP](https://arxiv.org/abs/2209.07753) | Prompt/Skill选择/API组合的奠基线 | 7–9h |
| 14 | [RAI](https://arxiv.org/abs/2505.07532) + docs | 类型化工具、ROS endpoint权限与Agent benchmark | 4–6h |
| 15 | [LeRobot论文/文档](https://arxiv.org/abs/2602.22818) | learned Skill数据与机器人adapter路线 | 4–6h |

建议总计约60–75小时；前7项读完再冻结论文题目。每篇笔记必须记录实验设置、baseline、失败、真实代码开放差距和可反驳我们的句子，不能只写摘要。

## 2. 第一优先级：必须下载测试

### A. OpenETA（1–3人日）

- 固定commit并记录仓库公开时间、第三方依赖和License。
- 跑官方 unit tests、batch manifest `--validate-only`、最小 `--once` 只读/仿真任务、replay。
- 审计：Tool/Skill separation、fresh-observation obligation、approval、安全门、evidence receipts、经验晋升，以及`real/`中观测driver与明确为stub的运动控制边界。
- 复现实验：先验证 README 的 LIBERO 配置是否可获得；不能复现则只把自报数值当项目结果。
- 不做：连接 Touch SDK、运行 real branch、授权世界动作。

### B. CaP-X（2–5人日）

- 固定commit/submodules；只装最轻仿真路径，不先装BEHAVIOR/Isaac。
- 跑1–2个官方最小任务，测安装时间、LLM/VLM调用、visual differencing、失败trace、skill synthesis产物。
- 确认CaP-Agent0/CaP-Bench接口是否可接受外部trace或新增API。
- 记录依赖冲突、模型/API成本和可复现性；不接真机。

### C. LeRobot（2–4人日，fake/replay）

- 官方安装和测试；fake robot/camera的record→load→replay round-trip。
- 核对Robot interface、action/state schema、相机时间戳/校准、dataset metadata和安全范围。
- 选ACT或Diffusion Policy做最小离线训练/推理预估；先测8GB GPU可行性。
- 后续Touch adapter另设安全任务，不在首次测试中动作。

### D. RAI（2–4人日）

- 在官方ROS2/容器仿真跑最小 typed tool；检查`args_schema`、可读/可写/forbidden endpoints、trace和benchmark。
- 目标是验证哪些概念值得重写进轻量Supervisor，不是迁移ThirdHand。

## 3. 第二优先级：条件测试

| 项目 | 条件 | 测什么 | 预计 |
|---|---|---|---:|
| HELIX/RHO | 有完全隔离、自动评分的synthetic/replay repo | coding-agent repository search、分支比较、tool-call/time成本 | 2–4日 |
| REFLECT | trace格式可转换 | failure summary、经验检索对离线规划的增益 | 1–3日 |
| VoxPoser | 3D/模型依赖可控 | 语言空间约束/value map，不接真机 | 2–5日 |
| BehaviorTree.CPP | 需要对照BT baseline | 在官方示例理解Retry/Fallback/Timeout；不必集成 | 0.5–1日 |
| MoveIt Task Constructor | Touch有可靠URDF/SRDF/ROS2 driver/ros2_control | 纯仿真Pick/Place task stages | 5–15日 |
| LERa | 作者补License或仅作独立研究复现 | PyBullet failure→explain→replan | 2–4日 |

## 4. 可延后或不建议当前测试

- openpi/π0.5：官方资源要求超过当前8GB推理余量；除非有远程大GPU和Touch数据。
- OpenVLA/Octo/RT：新embodiment训练/动作归一化成本高，且不回答Supervisor主问题。
- ReKep：无确认License、官方代码偏OmniGibson。
- PLanAR/ASPIRE/ENPIRE/Code-as-Monitor/DoReMi/CLASP：官方完整代码未确认，先读论文/项目页，持续监控开放状态。
- BEHAVIOR/OmniGibson/RoboCasa：重资产/Isaac/GPU与许可；仅当handoff仿真规模成为论文必要项。
- RLBench/LIBERO：只选一个做外部基线，避免同时维护旧栈；RLBench另有非商业许可。
- PDDL/PlanSys2与完整ROS2 Agent迁移：长程任务和可靠驱动出现后再测。

## 5. 每个仓库的统一测试卡

必须记录：URL、commit/tag、License和第三方许可、安装系统/Python/CUDA、安装时间与磁盘、测试命令与结果、模型/数据/API、峰值显存/内存、单步/episode时延、开放真机代码范围、支持的机器人/action space、失败issue、最小可复现任务、可抽取模块、Touch适配工时、是否污染现有环境。

## 6. 下载/测试的停止规则

- 无License且目标是复制代码；
- 官方最小测试在锁定环境连续两日无法运行且issue无解；
- 需要危险真机动作或不可撤销外部资源；
- 依赖链与当前GPU明显不匹配；
- 只能复现漂亮视频，拿不到可评分trace；
- 项目解决的是低层policy而非当前研究问题，继续投入不会改变论文判断。

## 7. 向老师先报备的必读结论

在任何下载测试前，老师至少应看到：OpenETA几乎完全重合；Semantic Handoff已直接命名问题；PLanAR已做真机stepwise verification；ASPIRE/CaP-X做自动Skill库；ENPIRE/RHO做Coding Agent策略改进。得到新Contribution认可后，才值得投入工程基线复现。
