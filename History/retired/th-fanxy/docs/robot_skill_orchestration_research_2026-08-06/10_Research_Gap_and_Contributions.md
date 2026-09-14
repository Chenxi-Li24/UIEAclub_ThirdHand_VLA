# 研究空白与论文 Contribution 重定义

## 1. 不能再讲的论文故事

不能以“构建 Codex/VLM + Skill Library + Vision + Retry/Replan + Memory 的真实机械臂系统”为主贡献。OpenETA 已把相同边界开源，PLanAR 是完整 plan-act-check-replan 真机论文，Semantic Handoff 直接研究 next-skill readiness，CaP-X/ASPIRE/ENPIRE/RHO 又覆盖代码策略、技能沉淀与自动改进。若仍按原故事投稿，审稿人很容易将其归为工程集成。

## 2. 推荐论文故事

### 推荐题目

**Evidence-Gated Skill Handoffs for Reliable Low-Cost Tabletop Manipulation**  
中文：**面向低成本桌面机械臂的证据门控 Skill 交接与有预算恢复**

### 一句话故事

现有 Agent/Skill 系统证明了“可以编排”，但链式真机执行仍会因不干净终态、低成本感知不确定和异构 Policy 的终态分布而失败；我们提出按证据充分性与风险选择规则检查、补观测或 VLM 的 verifier routing，并在 Touch R1 真实 handoff 基准上证明它以更少调用/更低时延减少危险误放行并提高有预算恢复成功率。

### 论文定位

优先定位为**方法 + 真实系统/基准**论文，而非通用 Agent 框架论文。核心算法必须脱离 Touch R1 代码细节仍可描述、可消融；系统是验证载体。

## 3. 建议的 4 项 Contribution

### C1. Evidence-Gated Verifier Routing

给定待验证谓词、规则/几何证据质量、观测新鲜度、视角、动作风险与剩余预算，路由器在以下动作中选择：`accept`、`fail`、`reobserve`、`alternate_view`、`invoke_vlm`、`human_review`。优化目标同时惩罚危险 false accept、false abort、时延、VLM 调用和额外世界动作。

**相对空白：** Code-as-Monitor 强调将语义约束编译为监视器，DoReMi周期调用VQA，OpenETA强调证据边界；但在低成本真机感知下，按风险/证据质量校准选择 verifier 的系统实证仍不充分。不能声称绝对首次，需以最新检索和强消融限定。

**验证：** 与 rule-only、VLM-only、always-VLM、fixed-period VLM、event-trigger without calibration 比较；报告 verifier 混淆矩阵、ECE/Brier（若有概率）、任务指标与调用成本。

### C2. Real-World Handoff Benchmark and Trace Dataset

构建 Touch R1 的 clean-start 与 chained-terminal-state 成对评测：同一 Pick/Place/Move/Recover Skill 在标准初态与前序 Skill 实际终态启动，记录 RGB/鱼眼、深度有效性、机器人状态、typed arguments、effects、readiness、失败分类和恢复轨迹。

**相对空白：** Semantic Handoff 已提出问题并在 BEHAVIOR-1K/π0.5 上诊断；我们的差异只能是低成本真实硬件、多传感器不完备、标定/遮挡/身份中断与异构 Policy。论文必须正面引用该工作，不能写“首次发现 handoff”。

**验证：** 测 clean→chained 成功下降、readiness false accept、失败传播深度；给出任务/对象/相机/标定/策略版本和可回放证据。

### C3. Cross-Policy Competence and Handoff Calibration

在统一 SkillContract 下封装 rule-based 与至少一种 learned policy（时间允许时 ACT 或 Diffusion Policy），为每个 policy variant 建立适用域、终态质量、尾延迟和 handoff readiness 的校准画像；选择/回退不是语言偏好，而是基于当前证据和经验可靠度。

**相对空白：** “多 Policy 共存”不新，CLASP/OpenETA 也支持技能/Policy 组合；可贡献的是跨 Policy 的同契约真实标定和选择误差分析。

**验证：** fixed policy、oracle policy、LLM-only selection、calibrated selection；分对象、初态和感知质量报告 success/latency/risk。

### C4. Budgeted Risk-Sensitive Recovery

把失败类别、动作幂等/可逆性、remaining world-change budget、证据不确定性和 next-skill readiness 纳入恢复策略，在重观测、重参数化、同策略重试、换 Policy、重规划、人工停止之间选择。

**相对空白：** Retry/Replan 已普遍存在，ENPIRE也报告上下文恢复；可成立之处是风险/证据/世界变化预算的明确目标与真实对比，而不是恢复阶梯本身。

**验证：** no recovery、fixed retry-N、always replan、BT fallback、proposed；报告 pass@1、budgeted success、recovery precision/success、额外动作、时间和安全事件。

## 4. 核心研究问题与假设

| RQ | 假设 | 主要证据 |
|---|---|---|
| RQ1：混合 verifier 能否比规则或VLM单独更可靠/高效？ | 风险/证据门控在相似false-accept下显著减少VLM调用和时延，或在相似成本下降低false-accept | verifier数据集 + 真机任务 |
| RQ2：clean Skill 能力能否预测链式成功？ | chained state显著降低成功；handoff readiness比局部effect更能预测下一步 | 成对handoff实验 |
| RQ3：统一契约能否跨异构Policy预测适用性？ | 校准选择优于固定/LLM-only，特别在扰动和边界状态 | rule + ACT/DP策略对比 |
| RQ4：预算恢复是否优于固定retry/replan？ | 风险敏感策略以更少世界动作获得更高budgeted success并降低危险重试 | 故障注入与恢复消融 |

## 5. 实验设计

### 任务层级

1. 单 Skill：Pick、Place、Move/Home、Open/Close gripper；
2. 两 Skill handoff：Pick→Place、Pick→Move-to-present；
3. 三至五步：取杯/瓶并放到指定区域、桌面简单整理、错误恢复后继续；
4. 不把倒水、刀具、易碎/高温物体放入首篇安全范围。

### 故障与扰动

- 目标偏移、边界放置、抓取点偏差、夹持滑落、遮挡/检测中断、深度无效/旧帧、相机视角不足、chain terminal pose不适合下一Skill、Policy timeout。
- 每种故障须有可控强度、注入日志和安全上限；不得为了论文危险地制造碰撞。

### Baselines

1. Rule-only + no recovery；2. fixed post-action rule checker；3. always-VLM；4. DoReMi式周期VLM；5. Code-as-Monitor式预定义/生成监视器；6. OpenETA式one-tool/fresh-observation loop；7. no-readiness vs readiness；8. fixed retry/always replan；9. clean-only competence selector。

OpenETA/CaP-X 若实测可运行，作为外部框架/仿真基线；否则严格说明接口重现而非官方代码结果。

### 指标

- 主指标：危险 false accept、任务 Pass@1、限定预算成功率、总完成时间。
- 次指标：false abort、UNKNOWN、恢复成功率、clean/chained gap、VLM calls/tokens、首动作/阶段/尾延迟、人工干预和额外世界动作。
- 报告置信区间；在冻结测试集前完成阈值和 prompt 调优，避免测试集追参。

## 6. 样本与统计建议

- 先用 replay/offline verifier 数据做 power estimate；不要直接拍脑袋定真机次数。
- 原型期最低可用设计：每个主要 condition × task 约30个 episode 是探索性下限，不足以宣称细小差异；最终按预实验方差/二项比例差计算样本量。
- 使用相同初态随机化清单做 paired/blocked comparison；记录所有失败和人工干预，不删“硬件异常”而应分层报告。
- 对模型型 verifier 至少重复不同随机种子/温度或使用确定性配置；锁定版本和 prompt。

## 7. 论文成功/失败判据

### 值得继续主线

- proposed routing 在危险 false accept 上显著更好，且不会以不可接受时延换取；
- clean/chained gap 在真机上稳定存在并可由 readiness 指标解释；
- 恢复提升不是无限重试带来的，额外世界动作和风险受控；
- 结果对至少两个任务、两个对象类/Policy 或两个 Planner 仍成立。

### 应及时转向

- 主要增益仅来自更强 VLM/model upgrade；
- 规则已解决全部任务，VLM/Planner没有可测价值；
- verifier error 大于恢复增益；
- learned Skill 无法在周期内稳定，拖累主实验；
- 只能胜过“无先验、自由生成几小时”的弱 baseline。

## 8. 与老师会议意图的对齐

新故事保留老师强调的“又好又快”、Prompt/先验、视觉介入、失败恢复、跨模型稳定和 rule-based P&P 先行；同时承认 2026 相关工作已使架构本身失去新颖性。Prompt 可作为路由输入/消融，Skill 库与平台是实验基础设施，不再宣称 Contribution。
