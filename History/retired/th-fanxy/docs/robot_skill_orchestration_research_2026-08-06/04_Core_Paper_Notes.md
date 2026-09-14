# 核心论文逐篇笔记

> 关注问题：是否已经覆盖“语言规划—Skill 调用—执行—视觉验证—Retry/换 Policy/Replan—记忆”；论文能力与官方开放代码分开判断。

## 1. ETA / OpenETA（2026）

- 论文：[ETA: A New Agentic Paradigm for Embodied Tasks](https://arxiv.org/abs/2608.03924)；代码：[OpenMOSS/OpenETA](https://github.com/OpenMOSS/OpenETA)。
- 方法：Planner 每次只选择一个 Tool；Interface/Host 执行并保留 schema、provenance、approval 与 safety 权限；World 返回结果和新观测。Tool 是宿主拥有的原子能力，Skill 是可读经验；完成一次有副作用动作后必须重新观测。
- 实验/开放：README 自报 `openeta-light` 上 Codex 在 130 个 LIBERO 任务达到 70.8% Pass@1、90.0% Pass@5；包含可替换 Planner、MCP/Tool、可回放轨迹、仿真适配和 UR5e/RealSense 真机目录。必须注意：`real/README.md` 明确写 `step_env`、`move_to`、`gripper_open/close` 等控制工具仍是 stub，只验证handle并返回观测，尚未开放完整真机动作闭环。仓库公开约两周，独立复现仍不足。
- 贡献：把 Agent/Host/World 三个权限边界、动作后新观测义务、工具完成与任务成功的证据区分、候选经验晋升流程做成开源栈。
- 局限：项目极新；README 结果主要是项目自报；公开真实控制仍是stub；Touch R1 未适配；第三方感知/抓取依赖各自 License；Agent 长时延和真实硬件安全仍需本地验证。
- 与我们关系：**整体架构几乎完全重合，是第一威胁和第一必跑基线。** “类型化工具、Skill/Tool 分离、Host 安全门、回放证据”均不能再单列为创新。
- 可复用：接口、日志、replay、approval/evidence boundary、真机观测抽象和 fake/sim 测试结构；不能复用不存在的完整真机控制，不替换 ThirdHand。

## 2. PLanAR（2026）

- 论文：[arXiv:2602.01662](https://arxiv.org/abs/2602.01662)；项目页：[PLanAR](https://planar-robot.github.io/)；官方页面标注代码尚未来。
- 方法：任务解析、对象 grounding、计划生成、primitive/Skill 执行、Action Checker、结果验证与重规划，使用多视角 RGB-D 支持真实机器人闭环。
- 实验：论文展示仿真与真实操控长程任务；重点不是单一 VLA，而是层级规划器与执行检查器的闭环组合。
- 贡献：把 plan-act-check-replan 形成一体化具身框架。
- 局限：当前无法从官方代码复现；多视角 RGB-D 与既有机器人栈投入明显高于当前 Touch R1。
- 与我们关系：全流程层面的直接先例。我们的架构图不能以“首次完整闭环”表述。
- 可复用：Action Checker 的职责边界、阶段化验证和实验对比设计；无代码可直接借。

## 3. Diagnosing Semantic Handoff Failures（2026）

- 论文：[arXiv:2607.06256](https://arxiv.org/abs/2607.06256)。
- 方法：在 BEHAVIOR-1K 中比较从干净快照启动单 Skill 与从前序 Skill 链式终态继续执行；使用 typed arguments、step budgets、多视图 VLM verification，显式诊断 next-skill readiness。
- 实验：核心不是判断某一 Skill 局部成功，而是观察它的终态是否满足下一 Skill 的语义需要；使用 π0.5 等 Skill 分析编排失败。
- 贡献：把“局部成功、全局不可继续”命名并给出诊断实验范式。
- 局限：以仿真为主；对低价传感器、真实相机遮挡、标定漂移、真实执行安全和异构 Skill 的实证仍有限；官方代码未确认。
- 与我们关系：**对原拟议语义交接创新最直接的威胁。** 可保留的空间是 Touch R1 真机数据、鱼眼/深度不完备、异构策略与校准验证路由，而非首次提出 handoff。
- 可复用：clean-vs-chained 实验、readiness 标签、失败分类与 step budget。

## 4. CaP-X（2026）

- 论文：[arXiv:2603.22435](https://arxiv.org/abs/2603.22435)；项目：[CaP-X](https://capgym.github.io/)；代码：[capgym/cap-x](https://github.com/capgym/cap-x)。
- 方法：CaP-Gym/CaP-Bench 统一多种仿真任务；CaP-Agent0 通过多轮观察、视觉差分和代码生成执行任务，并把可复用片段组织为 Skill library；另含强化/改进路线。
- 实验：覆盖 robosuite、LIBERO-PRO、BEHAVIOR 等 39 个任务，并给出真实 Franka bring-up 路径。
- 贡献：不只生成一段策略代码，而是提供适合代码式策略研究的环境、基准、Agent 和技能沉淀基础。
- 局限：Python/CUDA、Git submodule、互相冲突的 robosuite 版本、Isaac/BEHAVIOR 资产许可、SAM3 鉴权与模型 API 让安装面很大；仓库很新。
- 与我们关系：覆盖“Coding Agent + 视觉反馈 + 自动 Skill library”。它适合作 Baseline，不适合直接接管现有真机栈。
- 可复用：Tool/API 注册、代码执行边界、差分观察、Skill compilation 评测；优先在隔离 workstation 跑最小仿真。

## 5. ASPIRE（2026）

- 论文：[arXiv:2607.00272](https://arxiv.org/abs/2607.00272)；项目：[NVIDIA GEAR ASPIRE](https://research.nvidia.com/labs/gear/aspire/)；代码标注 coming soon。
- 方法：记录感知、规划、抓取、控制 primitive 的多模态 trace；Coding Agent 定位失败、修复代码策略、重执行验证，把通过的修复蒸馏到可检索 Skill library，并用进化搜索扩展任务。
- 实验：项目页展示 90+ Skills、150+ Tasks，覆盖 BEHAVIOR-1K、LIBERO、robosuite 和部分真实机器人。
- 贡献：把自动调试、验证、经验固化和持续 Skill 增长合在一个循环。
- 局限（作者明确）：依赖前沿大模型，固定 primitive API；需要可靠成功检测、安全重置、标定与安全设施；Memory 管理不完整；模型调用/搜索计算昂贵；代码尚未开放。
- 与我们关系：自动保存成功代码、自动修复和 Memory 都不能再单列创新。
- 可复用：trace 结构、候选 Skill 的 review/canary/holdout 晋升，而不是自动把一次成功直接写入生产库。

## 6. ENPIRE（2026）

- 论文：[arXiv:2606.19980](https://arxiv.org/abs/2606.19980)；项目：[NVIDIA GEAR ENPIRE](https://research.nvidia.com/labs/gear/enpire/)。
- 方法：Environment 自动 reset/verify，Policy Improvement 发起代码/训练改进，Rollout 在单臂或机器人 fleet 上预算执行，Evolution 分析日志、文献、训练基础设施和算法代码。
- 实验：真实 Push-T、插针、GPU/扎带等；项目页写 99% **pass@8**，含义是长程 rollout 内每个子任务最多 8 次有上下文恢复，不是一次执行成功率，也不是独立 best-of-8。
- 贡献：真实机器人上由 Coding Agent 管理可审计的自动研究循环；提出 MRU/MTU 资源指标。
- 局限：先决条件是自动重置和自动验证；机器人越多 token/协调成本越高，Agent 读日志/写代码时硬件利用率低；完整开放仓库未确认。
- 与我们关系：直接覆盖“Coding Agent 自动修改策略并比较真实成功率/时间”。
- 可复用：把 reset、verify、rollout budget、branch/history 当基础设施；当前团队不应追求自动真机策略演化。

## 7. RHO / HELIX（2026）

- 论文：[RHO](https://arxiv.org/abs/2606.16458)；代码：[HELIX](https://github.com/KE7/HELIX)。
- 方法：Coding Agent 在训练/搜索阶段提出和筛选多文件 Repositories-as-Policies，用环境 reward 和执行反馈优化；部署时单轮执行，避免 LLM 在实时控制环中多轮改代码。
- 实验：LIBERO-PRO、robosuite、RAI O3DE；论文报告在相同 primitive 下显著优于多轮代码 Agent/部分 VLA 基线，并减少运行时工具调用。
- 贡献：把策略从 prompt/单文件扩展为可进化的软件仓库；清晰分离离线搜索和在线控制。
- 局限：HELIX 是通用代码库优化器，不含 Touch R1 硬件安全、视觉或 reset；性能依赖可重复的环境 reward。
- 与我们关系：使“用 Codex 优化机器人策略仓库”不能作为新点；但支持“模型不进入高频真机环”的架构判断。
- 可复用：只在 synthetic/sim/replay 仓库做离线研究基线，不授权其直接执行 SDK。

## 8. Code-as-Monitor（2024/2025）

- 论文：[arXiv:2412.04455](https://arxiv.org/abs/2412.04455)；项目页：[Code-as-Monitor](https://zhoues.github.io/Code-as-Monitor/)；官方代码未确认。
- 方法：VLM 从语言任务和视觉中提取点/线/面等约束元素并生成监控代码；运行时用确定性代码连续检查，支持 reactive 与 proactive failure detection。
- 实验：项目页报告相对基线成功率增加 28.7%、执行时间降低 31.8%（项目方结果，应复现后使用）。
- 贡献：避免每帧直接询问 VLM，把语义理解编译为较快、可解释的监视器。
- 局限：生成的约束/感知仍可能错；开放代码未确认；3D单视角和遮挡仍是困难。
- 与我们关系：直接覆盖“执行中持续监控约束”，也是规则优先、VLM事件触发路线的最强理论依据。
- 可复用：constraint element、monitor lifecycle、reactive/proactive 标签与消融设计。

## 9. DoReMi（2023）

- 论文：[arXiv:2307.00329](https://arxiv.org/abs/2307.00329)；项目页：[DoReMi](https://sites.google.com/view/doremi-paper)。
- 方法：LLM 生成计划及自然语言执行约束；低层 Skill 运行期间周期调用 VQA 检查约束，失败则重规划。
- 实验：真实机械臂与人形/多任务演示；证明语言约束可在执行期间提供反馈。
- 贡献：把任务规划与过程约束监控连接起来。
- 局限：频繁 VQA 有延迟/成本，并可能因单视角3D理解不足误判；官方代码未确认。
- 与我们关系：持续视觉介入与失败重规划已被覆盖。
- 可复用：作为 always-VLM/periodic-VLM baseline；我们的贡献应是校准、低调用率且适合低成本传感器的路由。

## 10. CLASP（2026）

- 论文：[arXiv:2606.08169](https://arxiv.org/abs/2606.08169)。
- 方法：从每项 2–5 次动觉示教学习 task-parameterized movement policy；VLM 生成带参数、前置条件和语义说明的 Skill schema，再进行选择、绑定与组合；能力缺口时请求新示教。
- 实验：真实 7DoF 操控，重点评估语言驱动的新任务组合。
- 贡献：把 learned motion primitive 与可读 Skill schema 接合。
- 局限：需示教、TP-KMP 表示和已知对象参数；代码未确认；未重点解决低质量深度和部署安全。
- 与我们关系：结构化 Skill schema、选择、参数化、组合已高度覆盖；可把 ACT/DP/VLA 异构性和真实 handoff 验证作为差异。
- 可复用：schema 字段、capability gap、请求示教而非盲目生成动作的原则。

## 11. LERa（2025）

- 论文：[arXiv:2507.05135](https://arxiv.org/abs/2507.05135)；代码：[AmpiroMax/LERa](https://github.com/AmpiroMax/LERa)。
- 方法：failure detector 触发后，把当前 RGB、指令、初始计划送入 Look-Explain-Replan 模块，解释错误并产出修正计划。
- 实验：ALFRED/PyBullet 为主；项目材料报告 XArm6 + RealSense 15/18 试验。
- 贡献：用明确的视觉解释阶段避免直接无依据重规划。
- 局限：仓库规模很小、以仿真代码为主、未发现 License，真实机器人栈不清晰；checker 不完美时收益显著下降。
- 与我们关系：支持“checker 质量必须独立测量”；不能把视觉失败解释/重规划当新点。
- 可复用：失败样本输入格式和 checker-aware evaluation；代码不并入 ThirdHand。

## 12. REFLECT（2023）

- 论文：[arXiv:2306.15724](https://arxiv.org/abs/2306.15724)；代码：[real-stanford/reflect](https://github.com/real-stanford/reflect)。
- 方法：将多模态执行经验压缩成结构化/语言摘要，定位失败并给出纠正；后续任务使用过去经验。
- 实验：真实机器人任务，强调从失败中学习而非只做一次 Replan。
- 局限：感知、硬件和任务表示仍较定制，不能直接替代 Skill runtime。
- 与我们关系：Memory/失败摘要的基础相关工作。
- 可复用：事件时间线、failure cause、corrective action、evidence references 的日志字段。

## 13. CaP、ProgPrompt、SayCan、Inner Monologue（2022 基础组）

- [CaP](https://code-as-policies.github.io/) 证明 LLM 可组合感知/控制 API 生成代码；开放代码是 notebook/仿真示例，不是生产真机栈。
- [ProgPrompt](https://progprompt.github.io/) 用 imports、注释、示例和 assertions 表达能力/状态，说明 Prompt + precondition/recovery 早已出现；官方代码仅 VirtualHome 且许可证限非商业研究/评估。
- [SayCan](https://say-can.github.io/) 用语言概率与 affordance/value 对候选 Skill 排序，奠定“模型选择已训练 Skill”的范式；开放部分主要是模拟 tabletop。
- [Inner Monologue](https://innermonologue.github.io/) 把成功检测、对象/场景描述和人反馈持续送回 LLM，奠定闭环语言规划。
- 对我们：这四项共同使“LLM 根据语言调 Skill”“Prompt 提高选择正确率”“反馈后再规划”无法成为创新。可借的是 API 抽象、候选打分、断言和反馈类型。

## 14. RAI 与 ROS-LLM（框架组）

- [RAI](https://github.com/RobotecAI/rai) 是活跃的 ROS 2/LangChain 框架，工具具备 name、description、`args_schema`，并区分可读、可写、禁止的 ROS endpoint；支持仿真和部分实体机器人。
- [ROS-LLM](https://arxiv.org/abs/2406.19741) 研究 LLM 生成 action sequence、Behavior Tree、状态机，并从示教学习新动作/反思。
- 对我们：适合作为 ROS/Agent baseline 与权限设计来源；但 Touch R1 现有 Python SDK、闭环尚未稳定，完整 ROS 2 迁移会把研究时间耗在驱动、URDF、TF、MoveIt 和运维上。

## 15. VLA/学习策略组

- [LeRobot](https://github.com/huggingface/lerobot) 是数据、训练、策略与新机器人适配平台，应作为学习型 Skill 的首选接入层。
- [OpenVLA](https://github.com/openvla/openvla)、[openpi](https://github.com/Physical-Intelligence/openpi)、[Octo](https://github.com/octo-models/octo)、RT-1/2 是端到端或通用策略，不提供高层 Skill Supervisor。
- [Diffusion Policy](https://github.com/real-stanford/diffusion_policy) 与 [ACT/ALOHA](https://github.com/tonyzhaozh/aloha) 更适合封装为单个 learned Skill。
- 局限：新 embodiment 需要数据、动作归一化/坐标变换、训练与安全校验；openpi 官方需求表明 8GB GPU 当前不合适。
- 对我们：异构策略共存本身不新；可研究的是真实 handoff、能力边界、fallback 和校准验证。

## 16. 总体文献判断

最强证据链不是某一篇论文，而是：CaP/SayCan/ProgPrompt 已覆盖 API/Skill 选择，Inner Monologue/DoReMi/LERa/PLanAR 已覆盖视觉反馈与重规划，Semantic Handoff 已覆盖 next-skill readiness，CaP-X/ASPIRE 已覆盖技能沉淀，RHO/ENPIRE 已覆盖 Coding Agent 策略优化，OpenETA 已把这些边界公开成可运行框架。因此论文必须从“我们搭了这个闭环”转向“在特定真实约束下，我们提出并验证了何种更可靠/更高效的决策机制”。
