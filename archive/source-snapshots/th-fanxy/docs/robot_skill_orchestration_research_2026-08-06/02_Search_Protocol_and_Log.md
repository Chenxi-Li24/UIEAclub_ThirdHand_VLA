# 检索协议与日志

## 1. 范围、时间与原则

- 检索日期：2026-08-06（Asia/Shanghai）；“最近更新”是该日期快照。
- 主题：LLM/Coding Agent 调用机器人 Skill、结构化契约、视觉验证、失败恢复、语义交接、记忆/技能沉淀、异构策略、真实桌面操控与工程复用。
- 硬件约束：Touch R1 六自由度桌面臂、原厂 Python SDK、Lumos 鱼眼主视觉、D435i 临时深度、约两个月原型周期、本科团队维护。
- 证据优先级：官方论文/项目页/仓库/文档 > 官方 GitHub issue/discussion > 作者公开工程说明 > 第三方复现 > 社交媒体经验 > 营销与未验证技巧。
- 不以 Demo 代替代码检查；区分论文能力、仓库实际开放内容与 Touch R1 可用性。

## 2. 证据等级

| 等级 | 定义 | 可支持的结论 |
|---|---|---|
| A | 官方论文、项目页、仓库、许可证或维护者 issue | 方法、实验、开放状态、依赖和明确工程限制 |
| B | 作者/机构公开演示或开发文档，可回链项目 | 工程路径与自报结果；不能单独证明可复现性 |
| C | GitHub 用户 issue、第三方复现、论坛长文 | 失败模式和线索；需与官方信息交叉验证 |
| D | Reddit/X/视频评论、营销、无法定位版本的教程 | 仅形成待测假设，不进入关键事实结论 |

所有数值均尽量注明是论文结果、项目自报还是本次仓库快照。GitHub API 的 `open_issues_count` 同时包含 open issues 与 open PR，报告统一写作“open issues+PRs 快照”，不伪装成纯 issue 数。

## 3. 关键词簇

### 系统与 Skill

`LLM robot skill library`, `coding agent robotics`, `code as policy robotics`, `robot tool calling`, `structured robot skill schema`, `skill precondition postcondition`, `language model skill selection/composition`, `embodied agent skill orchestration`, `modular VLA skill composition`。

### 验证、交接与恢复

`VLM robot execution verification`, `visual failure detection`, `plan act verify replan`, `semantic handoff robot skills`, `next-skill readiness`, `runtime robot constraint monitor`, `failure recovery visual feedback`, `retry policy switch replan`。

### 经验与自动改进

`persistent robot memory`, `robot experience library`, `automatic skill compilation`, `coding agent optimize robot policy repository`, `real-world robot autoresearch`, `multimodal trace debugging`。

### 框架与硬件适配

逐项组合项目名与 `official`, `GitHub`, `license`, `real robot`, `new robot adapter`, `issue`, `install`, `Touch R1`, `ROS2`, `MoveIt`, `Isaac`, `OmniGibson`, `GPU memory`。

## 4. 检索平台与用途

| 平台 | 实际用途 | 纳入情况 |
|---|---|---|
| arXiv / CVF /论文项目页 | 核对方法、年份、实验、局限 | 核心证据 |
| GitHub 仓库/API/raw License | 核对官方代码、许可证、提交、分支、依赖、issue/PR | 核心证据 |
| 官方实验室/企业页 | NVIDIA GEAR、Google、Physical Intelligence、Hugging Face、Stanford 等 | 核心证据 |
| 官方文档 | LeRobot、RAI、MoveIt、BehaviorTree.CPP、Nav2、PlanSys2、仿真器 | 核心证据 |
| GitHub Issues | openpi 显存/Jetson、OpenVLA 数据与动作归一化、LeRobot 相机与校准 | 工程证据，注明用户报告属性 |
| Reddit/HN/X/Discord | 搜索部署和失败经验 | 多数不可稳定回链或缺版本；仅作线索，不承载关键结论 |
| YouTube/Bilibili/知乎/公众号/小红书/CSDN | 查演示、教程、中文经验 | 无法同时确认版本、代码和独立复现者被排除；项目方视频按“自报演示”处理 |

## 5. 逐轮检索日志

1. **输入核验：** 首轮附件只有任务说明；用户随后补传27页会议 PDF。逐页提取中文转写并以页码记录意图、噪声和不确定项；同时检查当前 ThirdHand 架构和既有视觉研究文档，确认硬件、Python SDK 与当前闭环风险。
2. **奠基工作：** 核对 CaP、ProgPrompt、SayCan、Inner Monologue、VoxPoser、ReKep、REFLECT、DoReMi 的论文、项目页和开放内容。
3. **2025–2026 直接威胁：** 检索 Code-as-Monitor、LERa、PLanAR、CLASP、Semantic Handoff、CaP-X、RHO/HELIX、ASPIRE、ENPIRE、ETA/OpenETA。
4. **Agent 框架：** 核对 RAI、ROS-LLM、长期 Skill/Memory 工作；判断是否有真实硬件、ROS 2 依赖和 Tool schema。
5. **VLA/学习型 Skill：** 核对 LeRobot、OpenVLA、openpi（π0/π0.5）、Octo、RT-1/RT-2、Diffusion Policy、ACT；检查显存、训练、动作空间与机器人适配。
6. **任务规划与执行：** 核对 MoveIt Task Constructor、BehaviorTree.CPP、Nav2 BT、PlanSys2/PDDL；区分设计可借鉴与短期迁移成本。
7. **仿真与基准：** 核对 RoboCasa、BEHAVIOR-1K/OmniGibson、RLBench、LIBERO、robosuite；检查许可证、资产/EULA、GPU/Isaac/CoppeliaSim 依赖。
8. **工程失败：** 检查 openpi Jetson/显存 issue、OpenVLA 自定义数据 issue、LeRobot 相机/校准 issue；从 CaP、Code-as-Monitor、LERa、ASPIRE、ENPIRE 官方页面提取延迟、误判、重置、验证和计算限制。
9. **交叉核对：** 以项目页链接反查 GitHub，以 README 反查论文，以 raw License 纠正 GitHub API `NOASSERTION`；没有官方代码的项目明确标“未确认开放”。
10. **综合：** 按“重合度、复用等级、威胁、适配难度”形成矩阵，避免把底层 VLA/仿真器误判为完整 Supervisor。

## 6. 代表性仓库快照

以下是 2026-08-06 的维护表面快照；计数会变化，不代表质量：

- OpenETA：18 commits，Apache-2.0，README 记录 2026-08-03 `openeta-light`；公开时间极短。
- CaP-X：MIT，最近推送 2026-05-28，open issues+PRs 约 8。
- HELIX：BSD-3-Clause，最近推送 2026-07-25，约 205 commits，open issues+PRs 约 5。
- RAI：Apache-2.0，最近推送 2026-07-22，open issues+PRs 约 121。
- LeRobot：Apache-2.0，检索当日仍有更新，open issues+PRs 约 710。
- openpi：Apache-2.0，最近推送 2026-06-16，open issues+PRs 约 317。
- ReKep、LERa：仓库未发现可确认 License；不应直接复制代码。
- ProgPrompt：官方仓库 License 是 NVIDIA 非商业研究/评估条款，不是通用开源许可证。
- RLBench：自定义非商业/学术用途许可证，不应写成 MIT。

## 7. 排除与降权规则

- 非官方 RT-2 复刻仓库、聚合型“awesome”列表、无论文/无代码的宣传页：不用于开放性结论。
- 项目页写“Code coming soon”：代码列写“未确认开放”，不根据搜索结果猜仓库。
- 只有仿真 demo 的仓库：不能写“开放真实机器人栈”。
- 只有真实机器人视频、无接口/配置/复现实验：按自报演示，不评为可直接复用。
- 无 License：即使代码可读，也不建议并入 ThirdHand。
- 旧依赖链与硬件专用 action space：降级为论文依据或局部参考。
- 社交媒体技巧若无法定位版本、作者或复现：只列待测试假设，不进入架构决策。

## 8. 局限与后续核验

1. 会议 PDF 是 ASR 转写而非原始音频；白板指向和大量术语仍无法仅凭文本恢复，已在01标“转写不确定”。
2. OpenETA、ASPIRE、ENPIRE 等在检索日前后快速更新，复用前需锁定 commit 并重新审计。
3. 本轮按要求未 clone、安装或运行第三方代码；“可运行性”是基于官方材料和 issues 的预评估，不是实测结论。
4. 私有 Discord/X 帖和不可搜索讨论无法形成可审计证据。
5. Touch R1 驱动、URDF、关节/笛卡尔接口的公开程度未知；适配工时是区间判断，需以最小 fake/replay adapter 实测校正。
