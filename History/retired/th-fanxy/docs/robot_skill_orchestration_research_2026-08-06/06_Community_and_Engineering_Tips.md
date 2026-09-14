# 社区证据与可直接借用的工程技巧

本文件覆盖 GitHub Issues/README、作者工程说明、社交媒体线索及其可信度分层。

## 1. 证据说明

本轮没有用无法稳定定位的 X/Discord/小红书/群聊内容支撑关键结论。可审计的“社区经验”主要来自官方 GitHub issues、README 中的失败说明和作者项目页。项目方视频/成功率按“作者自报”而不是独立复现处理。

| 证据 | 观察 | 类型/可信度 | 对 ThirdHand 的含义 |
|---|---|---|---|
| [openpi README](https://github.com/Physical-Intelligence/openpi) | 官方列出推理 >8GB、LoRA >22.5GB、完整微调 >70GB 显存级别，并警告自定义机器人设置可能不工作 | 官方工程事实，A | 8GB GPU 不把 openpi 作为两月主线；先做 Supervisor 与非学习闭环 |
| [openpi issue #826](https://github.com/Physical-Intelligence/openpi/issues/826) | Jetson 部署出现 GPU/CPU fallback、性能和 patch/依赖兼容问题 | 用户报告，C；具体版本需复现 | “模型能加载”不等于边缘端达到控制频率；推理应远离高频安全环 |
| [openpi issue #379](https://github.com/Physical-Intelligence/openpi/issues/379) | 用户报告 RTX 4090 上 LoRA OOM | 用户报告，C | 实际峰值内存可能高于表格；必须做本机 preflight 而非按参数量估算 |
| [OpenVLA issue #312](https://github.com/openvla/openvla/issues/312) | 自定义 WidowX 数据、action representation/normalization 和微调流程存在易错点 | 用户报告，C | 新 embodiment 最大风险是动作语义与归一化，不是只换 robot name |
| [LeRobot issue #3134](https://github.com/huggingface/lerobot/issues/3134) | 相机 backend、RealSense timeout、标定与深度支持仍是高频工程问题 | 社区/维护讨论，B/C | 相机时间戳、断流、深度有效率和 calibration lifecycle 必须独立测试 |
| [CaP 项目页](https://code-as-policies.github.io/) | 作者演示中模型 API 查询会造成明显等待；代码策略依赖外部能力 API | 作者说明，B | LLM/Codex 不进入控制周期；只在任务/子目标边界调用 |
| [Code-as-Monitor 项目页](https://zhoues.github.io/Code-as-Monitor/) | 指出频繁直接 VLM/VQA 检查会受有限 3D/单视角理解影响而误判 | 作者研究结论，A/B | 规则/几何连续监视，VLM只处理语义歧义与事件边界 |
| [LERa 项目页](https://lera-robo.github.io/) | 不完美 failure checker 会明显削弱 replanning 收益 | 作者实验，A/B | 必须单测 verifier 的 false accept/false abort，而不是只看总成功率 |
| [ASPIRE 项目页](https://research.nvidia.com/labs/gear/aspire/) | 自动修复依赖可靠 success detector、安全 reset、标定、固定 primitive API 和强模型；计算/调用成本高 | 作者限制，A | 自动沉淀 Skill 是最后阶段，先建立可验证环境与候选晋升机制 |
| [ENPIRE 项目页](https://research.nvidia.com/labs/gear/enpire/) | 真机 autoresearch 的前提是自动 reset、自动 verify、审计 rollout；fleet 会增加 token/协调成本 | 作者限制，A | 没有 reset/verify，就不能安全宣称 Coding Agent 会自动优化真机 |
| [OpenETA README](https://github.com/OpenMOSS/OpenETA) | Tool completion、world change、task success 是三种不同声明；副作用动作后必须新观测 | 官方设计，A | SDK 返回“command complete”绝不能当成抓取/放置成功；每个 effect 有证据 receipt |

## 2. Skill 表达：当前推荐

### 选择：Python host + JSON Schema/typed data，暂不选 PDDL 或 C++ BT runtime

- 对外：模型只看到版本化 Skill manifest 和 JSON Schema；来源是 OpenETA 的 typed tools、RAI 的 `args_schema` 与 ProgPrompt 的 API/断言思想。
- 对内：轻量 Python Supervisor 执行小型状态机/BT 语义；`Sequence`、`Fallback`、`Retry`、`Timeout`、`Guard` 可借 [BehaviorTree.CPP](https://www.behaviortree.dev/) 定义，但不用引入 C++。
- PDDL：只有当任务达到长程、对象/房间状态多、需要显式 domain planner baseline 时再加 [PlanSys2](https://plansys2.github.io/)；3–8 步桌面任务先用 typed plan。
- Skill 不等于任意 Python 文件；host 才拥有 SDK，模型只能提议已注册能力和参数。

## 3. 白名单、类型和坐标安全

1. **双层 allowlist：** Planner 可见技能清单；Executor 还有不可被 Planner 修改的 SDK 方法 allowlist。来源：[OpenETA](https://github.com/OpenMOSS/OpenETA) Host-owned supervision、[RAI](https://github.com/RobotecAI/rai) readable/writable/forbidden endpoints。
2. **严格类型：** 所有标量带单位、所有位姿带 frame、时间带 clock/source、图像带 camera/frame_id；不允许裸数组猜语义。
3. **schema 后再语义检查：** JSON 类型正确不代表空间有效；还需 workspace、速度、负载、可达性、标定版本和对象新鲜度检查。
4. **版本绑定：** Plan 记录 Skill 版本、模型/Prompt 版本、标定 hash、相机配置；Trace 才可重放。
5. **拒绝自动补值：** 缺 frame、单位、置信度或目标对象歧义时返回结构化错误，让 Planner 重新观察/询问，不用默认值“帮忙”。

## 4. 何时用规则，何时用 VLM

| 检查 | 首选 | VLM介入条件 | 理由/来源 |
|---|---|---|---|
| 关节/速度/工作空间/超时 | 确定性规则 | 不介入 | 安全不交给概率模型；OpenETA/RAI权限边界 |
| 目标是否仍在ROI、深度是否有效 | 检测+几何+新鲜度 | 多对象歧义、遮挡恢复 | 现有感知可审计；减少调用 |
| Grasp 是否闭合 | 夹爪宽度/电流（若SDK有）+目标随动/抬升后位置 | 证据冲突 | 单一图像易受遮挡；Code-as-Monitor思想 |
| 对象是否掉落 | 轨迹间目标关联、夹爪证据、桌面区域重新出现 | 多视角仍冲突 | 持续规则监控更快 |
| Place 是否稳定 | 速度接近零、目标与区域关系、连续N帧一致 | 语义容器/复杂遮挡 | 防止一帧 Yes/No 抖动 |
| 下一 Skill readiness | typed preconditions + world-state predicates | 需要语义关系/未建模对象 | Semantic Handoff直接相关 |
| 全局任务是否完成 | 组合效果谓词 | 规则证据不足时事件触发 | 区分tool complete与task success；OpenETA |

### 避免 Yes/No 连续误差

- 不在每帧问“成功了吗”；给 VLM 结构化证据包：任务、前后关键帧、多视角、检测/深度摘要、待验证谓词和允许输出枚举。
- 要求输出 `PASS | FAIL | UNKNOWN` 加可定位证据，不把低置信“YES”当成功。
- 用时间滞回：规则需连续 N 帧成立；VLM 只在状态变化后或规则冲突时触发。
- VLM 不决定安全动作，只返回语义判定；Recovery Manager 依据预算与权限选择动作。
- 对同一 verifier 单独构建混淆矩阵并校准阈值。依据：LERa checker sensitivity、Code-as-Monitor 对频繁 VLM 的批评。

## 5. 固定相机、腕部/近视角与深度缺失

- 当前 Lumos 固定鱼眼适合全局状态、对象/区域关系和掉落检测；D435i 暂时提供局部深度。先明确每个 predicate 的“证据相机”，不要无条件融合。
- 如果后续有腕部/近视角：只在抓取前定位、遮挡后验证和 placement 细节触发；多视角必须带时间戳并避免把不同时间的世界状态当同步观测。
- 深度缺失时不填 0、不沿用过旧深度；返回 `UNKNOWN`，可重观测/改视角/退回 2D 安全任务。对点云/位置使用有效率、方差和标定版本。
- 鱼眼图像需记录去畸变模型/ROI；用原图检测坐标与去畸变/深度坐标时必须显式转换，不能混 frame。

## 6. Retry、换 Policy 与 Replan

建议有界恢复阶梯：

1. `reobserve`：获得新鲜状态，解决旧观测/短遮挡；
2. `reparameterize`：同一 Skill 调整抓点/放置点/视角；
3. `retry_same_policy`：仅对幂等或已确认安全回退的动作；
4. `fallback_policy`：规则 → learned 或 learned → rule，必须重新检查 preconditions；
5. `replan`：世界状态/目标改变或候选 Skill 不再适用；
6. `human_stop`：预算耗尽、证据冲突、安全不确定或无恢复路径。

每层有次数、时间和世界变化预算；禁止无限自循环。Skill 局部成功后仍要检查 handoff readiness，不能直接进入下一步。来源：Behavior Tree Retry/Fallback 语义、Semantic Handoff step budgets、OpenETA bounded turns、ENPIRE pass@8 的恢复解释。

## 7. Trace、Memory 与真实失败数据集

每次动作记录：任务/episode、Skill/Policy/Prompt/model 版本、输入 schema、坐标系与标定 hash、前后多视角帧、深度有效性、SDK command/receipt、规则 predicate、VLM request/response、资源锁、超时、错误分类、恢复选择、人工干预和最终 outcome。

Memory 分三层：

- immutable evidence：不可改的原始执行证据；
- episode summary：可重算的事件/失败摘要（借 REFLECT）；
- promoted experience/Skill hint：只有经过 review、canary、holdout 后晋升（借 OpenETA/ASPIRE），带适用范围和失效条件。

真实失败数据集主动注入：目标偏移/遮挡、无效深度、抓取滑落、place 边界、下一 Skill 所需姿态不满足、相机短断流、旧观测、Policy timeout。所有注入先 replay/道具安全设置，真机注入需另行安全批准。

## 8. 应测指标

- 任务：Pass@1、限定预算成功率、总时间、首动作延迟、平均/尾部阶段延迟。
- 恢复：失败检测召回率、恢复触发精度、恢复成功率、平均 retries、replan 次数、预算耗尽率。
- Verifier：false accept（危险）、false abort（效率）、UNKNOWN率、校准误差、每次判定时延。
- Handoff：clean-snapshot 与 chained-state 的成功差、readiness false accept、失败传播深度。
- 成本：VLM calls/episode、tokens、GPU/CPU时间、人工干预次数。
- 安全：工作空间拒绝、超速/超时、急停、未授权调用、无新观测继续动作次数（目标为0）。

## 9. 社交媒体结论

X/Reddit/Discord/Bilibili 等可以发现新项目和失败线索，但本轮未发现同时具备稳定链接、版本、硬件、配置与复现记录、且会改变上述决策的社区证据。后续若采用某条技巧，应把它先转化为可证伪试验，不把点赞、播放量或单段成功视频当可靠性证据。
