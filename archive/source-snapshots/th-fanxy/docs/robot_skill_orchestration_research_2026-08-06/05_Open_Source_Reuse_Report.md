# 开源复用与 Touch R1 适配报告

## 1. 母框架决定

**代码母体继续使用当前 ThirdHand。** 原因不是外部框架不先进，而是已有系统已经包含 Touch R1 Python SDK、目标检测、深度/三维坐标、抓取状态机和界面；当前 P0 风险集中在相机接入、真实深度主路径、姿态解释、标定、状态机完成语义和浏览器动作链。迁移 OpenETA/RAI/ROS 2 不会消除这些硬件事实，反而增加适配面。

外部项目应按三种方式进入：

1. **隔离基线：** OpenETA、CaP-X、HELIX 在独立环境/仿真/replay 中运行；
2. **模块层：** LeRobot 提供数据与学习策略，现有 ThirdHand 提供真机 adapter；
3. **设计层：** RAI/OpenETA 权限与 schema、BehaviorTree.CPP 恢复语义、REFLECT trace、Code-as-Monitor 监控器。

## 2. 优先仓库审计

| 项目 | 仓库/License | 安装与依赖预判 | 可复用模块 | Touch R1 方案 | 结论 |
|---|---|---|---|---|---|
| OpenETA | [GitHub](https://github.com/OpenMOSS/OpenETA)，Apache-2.0 | Python 3.10+、`uv sync --extra dev`；真机extra为`uv sync --extra real`；模型 endpoint；各仿真/感知 extra 独立 | Tool/Skill separation、AtomAction、fresh-observation、approval、replay、evidence/experience promotion、真机观测抽象 | `real/`已有RealSense/UR5e观测/driver，但MCP运动控制工具明确仍是stub；先只做fake/replay/只读观测映射，不让Agent直连SDK | A：第一必跑架构参照，但没有可直接复用的完整真机运动闭环 |
| CaP-X | [GitHub](https://github.com/capgym/cap-x)，MIT | `uv`、submodules、多版本 robosuite；BEHAVIOR 要 Isaac/资产；SAM3/API 可能鉴权 | CaP benchmark、API registry、visual differencing、Skill compilation | 仅在 robosuite/LIBERO 最小环境跑 baseline；将 ThirdHand trace 离线转换为其评测输入，而非接真机 | A：研究基线，安装风险高 |
| LeRobot | [GitHub](https://github.com/huggingface/lerobot)，Apache-2.0 | 当前 Python/torch/camera backend；版本更新快；按官方 robot/camera 文档锁 commit | Dataset、record/replay、ACT/DP/SmolVLA 等策略接口、Robot abstraction | 写最薄 `TouchR1Robot`/camera adapter；先 fake robot + 记录 round-trip，再只读状态，最后才是人工门控动作 | A：学习型 Skill 与数据层 |
| RAI | [GitHub](https://github.com/RobotecAI/rai)，Apache-2.0 | ROS 2、LangChain、Docker/仿真与消息接口；部署面大 | `args_schema`、tool name/description、可读/可写/forbidden endpoint、benchmark ideas | 不迁移；把 endpoint 权限映射为 SDK allowlist/capability token | B：借接口与权限模型 |
| HELIX | [GitHub](https://github.com/KE7/HELIX)，BSD-3-Clause | 通用 coding-agent harness；需要可自动评测的软件环境与 token 预算 | repository search、分支/候选比较、离线反馈 | 只对 synthetic/replay supervisor 仓库做离线搜索；禁止访问硬件凭证/SDK | B：自动改进研究基线 |
| REFLECT | [GitHub](https://github.com/real-stanford/reflect)，MIT | 研究代码/模型 API/任务数据，需局部移植 | 多模态经验摘要、失败因果字段 | 只抽取日志 schema/prompt，输入 ThirdHand replay，不移植硬件代码 | B |
| VoxPoser | [GitHub](https://github.com/huangwl18/VoxPoser)，MIT | VLM/LLM、3D perception/value maps、运动规划环境 | 空间关系/约束表示 | 可离线试值图或语言到空间约束；不进第一阶段闭环 | B/C |
| ReKep | [GitHub](https://github.com/huangwl18/ReKep)，无确认License | OmniGibson、OpenAI API、优化器 | 关系关键点约束概念 | 不复制代码；只在仿真研究后评估 | C |
| LERa | [GitHub](https://github.com/AmpiroMax/LERa)，无确认License | 仓库偏 ALFRED/PyBullet，真实控制不完整 | Look-Explain-Replan 数据流 | 可用自己的 replay 重现论文 baseline，不复制代码 | C |
| ProgPrompt | [GitHub](https://github.com/NVlabs/progprompt-vh)，非商业研究许可 | VirtualHome；旧且代码少 | imports/examples/assertions 提示结构 | 只借论文思想并重新实现通用 prompt baseline | C |
| Diffusion Policy | [GitHub](https://github.com/real-stanford/diffusion_policy)，MIT | 训练数据、GPU、UR5/D415示例、依赖版本 | learned Pick/Place policy | 优先使用 LeRobot 中更易维护的实现；需 Touch 动作数据 | B（后期） |
| ACT/ALOHA | [GitHub](https://github.com/tonyzhaozh/aloha)，MIT | ALOHA双臂硬件耦合、示教/训练 | ACT算法/基线 | 走 LeRobot ACT，封装为单个 Skill | B（后期） |

## 3. 不建议短期接入的项目

### OpenVLA / openpi / Octo / RT 系列

它们是低层视觉到动作策略，不解决 Skill 契约、执行权限、结果验证或恢复。Touch R1 需要新的观测/动作空间、归一化统计、数据和训练。尤其 [openpi](https://github.com/Physical-Intelligence/openpi) 官方 README 对推理给出大于 8GB 显存要求，LoRA 大于 22.5GB；当前 8GB GPU 没有余量。可作为论文背景或远期单 Skill，不作为两月原型核心。

### MoveIt Task Constructor / ROS 2 全栈

[MTC](https://github.com/moveit/moveit_task_constructor) 本身成熟，但需要可信 URDF/SRDF、关节限位、碰撞模型、运动学、TF、ros2_control 和 Touch R1 驱动。当前核心障碍是相机、深度、姿态、标定和真机状态语义，先迁移会把科研问题变成基础设施项目。条件成熟后，MTC 可作为 motion/task planning backend，不做 Agent Supervisor。

### BEHAVIOR-1K / OmniGibson / RoboCasa / RLBench / LIBERO

它们适合作仿真论文基准，不是实机代码母体。BEHAVIOR/OmniGibson 依赖 Isaac/资产许可与重 GPU；RoboCasa 有大量资产；RLBench 受自定义非商业许可证和 CoppeliaSim/PyRep 约束；LIBERO 依赖较旧且仍需 robosuite。短期只选择一个最小仿真基线，避免同时维护多个环境。

## 4. 适配工作量估计

这是未实际安装前的工程区间，单位为熟悉 Python/机器人接口的有效人日，不含真实硬件排队：

| 目标 | 最小可证伪试验 | 人日 | 主要风险 |
|---|---:|---:|---|
| OpenETA 本地 CLI + fake/replay tool | 跑测试、validate-only、一次只读 replay | 1–3 | 项目极新、接口变动、模型配置 |
| OpenETA → Touch 只读观测 adapter | 相机/状态以 typed receipt 返回，不动作 | 2–5 | 坐标/图像生命周期与设备并发 |
| CaP-X 单一 robosuite 环境 | 固定 commit 跑最小任务 | 2–5 | submodule/依赖冲突、模型 API |
| LeRobot fake robot + dataset round-trip | record→load→replay，不接真机动作 | 2–4 | 相机后端、时间戳、数据 schema |
| LeRobot Touch R1 adapter | 状态读出、动作限幅、急停模拟、单 Skill | 5–12 | SDK语义、频率、标定、安全 |
| RAI 最小工具示例 | ROS2仿真/无硬件 | 2–4 | ROS发行版、Docker/GPU |
| 完整 RAI/ROS2 迁移 | 现有能力等价迁移 | 20–45+ | 驱动/URDF/TF/MoveIt/运维 |
| MTC 真机 Pick-and-Place | 规划、碰撞、执行 | 15–35+ | 缺可靠机器人模型与驱动 |
| openpi/OpenVLA 新embodiment | 单 learned Skill | 20–60+ | 数据、训练、GPU、动作归一化 |

## 5. 计划安装方式（本轮未执行）

所有第三方试验必须放在独立目录/环境，固定 commit，记录 GPU/驱动/模型版本，先执行其官方 unit tests 或 validate-only，再跑最小仿真；不得把依赖直接装进 ThirdHand 环境。

1. OpenETA：按 README 使用 Python 3.10+ 与 `uv sync --extra dev`；先 `pytest`、manifest `--validate-only`、read-only/once 模式，再评估 `openeta-light` 和 real 分支。
2. CaP-X：clone 时初始化官方 submodules；只选官方最轻的 robosuite/LIBERO 路径；不先装 BEHAVIOR/Isaac；记录 API/SAM 权重与许可。
3. LeRobot：按当日官方安装文档锁版本；先 fake robot/camera 和数据 round-trip；不得跳过 calibration、action range、timestamp 与 emergency stop 测试。
4. RAI：只在官方支持的 ROS 2 发行版与容器/仿真运行 tool schema 示例；不接 Touch。
5. HELIX：提供没有密钥、没有 SDK、可自动评分的 synthetic/replay repo；审计 Agent 可修改的路径和命令。

这些是后续“必须实际下载测试”的方案，不代表本轮已经安装或验证可运行。

## 6. License 决策

- 可研究与再开发：Apache-2.0、MIT、BSD-3-Clause，但仍需保留 notice 并核第三方模型/数据许可证。
- ProgPrompt：官方条款仅非商业研究/评估，不能按普通开源代码处理。
- RLBench：自定义非商业/学术条款，不能宣称 MIT。
- ReKep、LERa、PLanAR、Code-as-Monitor、DoReMi 等若没有确认代码/License：只读论文与公开材料，不复制实现。
- OpenVLA/openpi 等：代码许可不等于模型权重/基础模型/数据许可；必须逐项核对。

## 7. 最终复用等级

- **S：** 现有 ThirdHand（唯一母体）。
- **A：** OpenETA（外部架构/基线）、CaP-X（研究基线）、LeRobot（数据与 learned Skill）、现有本地视觉/SDK模块。
- **B：** RAI、HELIX、REFLECT、VoxPoser、BehaviorTree 语义、Diffusion Policy/ACT、MTC（条件成熟后）。
- **C：** ProgPrompt、ReKep、LERa、PLanAR、DoReMi、Code-as-Monitor、CLASP、重型仿真器，作为论文/设计依据。
- **D：** 当前直接部署 openpi/OpenVLA/Octo/RT、把 BEHAVIOR/OmniGibson 或完整 ROS 2 迁移当两月主线。
