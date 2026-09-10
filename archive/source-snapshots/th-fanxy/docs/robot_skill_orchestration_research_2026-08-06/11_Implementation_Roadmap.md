# 实施路线图（仅规划，本轮未执行）

> 前提：本文件描述老师确认后的未来工作。本轮没有写代码、改运行系统或操作机械臂。任何真机步骤都需另行审批、安全检查和现场人员。

## 阶段 0：开工前决策门（1–2天）

### 目标

- 向老师报告 OpenETA、PLanAR、Semantic Handoff、CaP-X、ASPIRE、ENPIRE、RHO 的直接威胁。
- 确认新论文题目、3–4项Contribution、任务范围、Baseline、时间、真机安全和数据公开边界。
- 补确认会议白板上页19“这和这”具体指向。

### 验收

- 一页签字/邮件确认的研究问题、主指标和“不做清单”；
- 明确选择“方法+基准”或“系统论文”；
- 没有确认则不进入真机自主执行。

## 两周：最小可证伪闭环与离线证据

### 第1–2天：冻结任务与契约

- 选1个 Pick-and-Place 主任务、2–3种对象、1个目标区域；定义成功/失败/UNKNOWN。
- 冻结 SkillContract v0.1、坐标/单位/frame、错误分类、effect/readiness谓词、安全边界。
- 定义4类故障注入和 clean/chained 初态协议。

**依赖：** 老师确认；现有硬件接口说明和相机标定信息。  
**验收：** 每个谓词能由明确证据判定；`command_complete`不等同task success。

### 第3–4天：Dry-run / Replay 基线设计

- 设计不接真机的 fake observation、recorded-frame replay 和 command receipt。
- 列出 Rule-only、post-action checker、always-VLM、event-triggered hybrid 的相同输入输出。
- 设计所有错误路径：stale frame、invalid depth、timeout、unknown object、unsafe pose。

**验收：** 一套 trace 可重放并复算 verifier 结果；未授权路径不能产生动作。

### 第5–6天：数据与标注协议

- 从已有安全录制/静态摆拍中组织 before/after、多视角/深度摘要；不自动运动。
- 建立 effect、readiness、failure cause、evidence quality 标签说明和双人复核样本。
- 先做 verifier confusion matrix 和 inter-annotator agreement。

**验收：** 至少覆盖 PASS/FAIL/UNKNOWN、遮挡、深度无效和身份中断；标签可追溯到帧。

### 第7–8天：离线 Baseline 与 Prompt 冻结

- 在 replay 上比较规则、VLM-only、always-VLM、structured evidence prompt。
- 冻结模型、prompt、temperature、timeout、JSON输出和异常处理；测试不同问法只在train/dev完成。

**验收：** 测试集前冻结；报告false accept/abort、UNKNOWN、时延和调用成本，不只报accuracy。

### 第9–10天：路由与恢复策略纸面/Replay消融

- 用证据质量、动作风险与预算设计 verifier routing 和恢复决策表。
- replay/synthetic fault 比较 fixed retry、always replan、budgeted ladder。
- 形成“真机前 Go/No-Go 报告”。

**验收：** 所有循环有终止；UNKNOWN fail-closed；有安全/权限/日志测试清单。没有通过则保持离线。

## 一个月：受控真机基线（需另行授权）

### 第3周

- 修正/验证现有相机、深度、姿态、标定、跟踪和状态机 P0问题。
- 仅在人工逐动作批准下跑 rule-based P&P；建立真实帧/状态/receipt trace。
- 标定 clean-start 单 Skill 成功率；不接 Codex自动动作。

### 第4周

- 加 effect 与 handoff checker；做少量安全扰动和 chained-state 对比。
- VLM仅离线或shadow mode，不控制动作；比较规则和VLM判定。
- 若 verifier 达到预定门槛，再允许“模型提议—人工批准—执行”的低速闭环。

### 一个月验收

- rule-based P&P 在冻结任务/初态下有稳定基线和置信区间；
- 100%动作有trace、版本和证据；0次未授权SDK调用/无新观测继续；
- handoff gap 可测，或有证据否定该研究假设；
- 形成可预注册的两月实验方案。

## 两个月：方法消融与异构 Skill

### 第5–6周

- 实现/验证 evidence-gated verifier routing；逐步启用 supervised recovery。
- 与 rule-only、always-VLM、fixed-period/event baseline 做 paired trials。
- 下载审计 OpenETA、CaP-X、LeRobot、RAI；在隔离环境跑最小官方测试/仿真。

### 第7周

- 若数据、算力和安全均达标，通过 LeRobot 接入一个 ACT 或 Diffusion Policy Skill；否则保留多个 rule policy variant，避免拖垮论文主线。
- 评估同一 SkillContract 下的policy适用域、终态分布和fallback。

### 第8周

- 冻结系统和测试集；完成真机主实验、失败案例、统计与消融。
- 整理匿名/脱敏 trace、数据卡、License和复现实验说明。
- 对最新论文/仓库再做一次 novelty scan，尤其 OpenETA/ASPIRE/ENPIRE。

### 两个月验收

- 至少3个任务/组合、明确的clean/chained实验、足够样本与置信区间；
- proposed method相对强baseline在风险—成功—时延—调用成本上有可辩护Pareto改进；
- 所有失败都进入分类，不因硬件异常被静默删除；
- 论文Contribution不依赖“我们搭了一个Skill库”或某一模型版本。

## 暂缓事项

- 完整 ROS 2/RAI/MoveIt 迁移；PDDL domain；BEHAVIOR/OmniGibson重型仿真；全屋/厨房任务；倒水/刀具/易碎品；openpi/OpenVLA大模型训练；Coding Agent真机自动改代码；自动把一次成功晋升Skill；无人工安全门的自主真机运行。

## 风险与替代路径

| 风险 | 触发条件 | 替代 |
|---|---|---|
| 当前闭环不稳定 | rule P&P无法形成可重复基线 | 把论文先聚焦感知/effect verifier数据与dry-run，不强接Agent |
| VLM无增益 | 规则已覆盖或VLM误判高 | 研究何时“不应调用VLM”，将门控节省/安全作为结果 |
| learned Skill延期 | 数据/训练/适配不稳定 | 两个不同rule/policy variant做fallback；learned policy列后续 |
| OpenETA快速追平 | 新release覆盖拟议方法 | 采用其为母baseline，贡献转向真实handoff数据/校准算法 |
| 真机样本不足 | 安全/时间限制 | 加强paired design与replay，诚实定位pilot/benchmark，不夸大统计 |
| 相机/深度不可用 | 断流、无效深度、鱼眼标定差 | UNKNOWN/fail-closed；固定ROI/对象；先替换相机再做实验 |

## 每周必须产出的证据

不是“做了多少模块”，而是：冻结commit/配置、任务与初态清单、trial manifest、trace数量、成功/失败分布、verifier混淆矩阵、延迟/调用成本、已知故障、未解决风险和下一周Go/No-Go。
