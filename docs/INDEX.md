# Documentation Index

这是 ThirdHand VLA 的文档总入口。先按任务选择文档，再进入模块目录查看实现细节。

## 操作与验证

| 我要做什么 | 阅读 |
|---|---|
| 启动、停止、检查状态和排障 | [`RUN_GUIDE.md`](RUN_GUIDE.md) |
| 查看运行时所有权与安全约束 | [`OPERATIONS.md`](OPERATIONS.md) |
| 查看待迁移能力、目标目录和 History 删除门槛 | [`MIGRATION_BACKLOG.md`](MIGRATION_BACKLOG.md) |
| 查看语音、模型到真机执行的完整安全链路 | [`VOICE_ACTION_CONTROL_CHAIN_DESIGN.md`](VOICE_ACTION_CONTROL_CHAIN_DESIGN.md) |
| 按测试优先步骤实施语音到夹爪的授权闭环 | [`VOICE_GRIPPER_CONTROL_IMPLEMENTATION_PLAN.md`](VOICE_GRIPPER_CONTROL_IMPLEMENTATION_PLAN.md) |
| 检查本机 SDK、模型、运行时与哈希 | [`../local/README.md`](../local/README.md) |
| 查看完整目录职责 | [`DIRECTORY_MAP.md`](DIRECTORY_MAP.md) |
| 查阅测试与验证命令 | [`../tests/README.md`](../tests/README.md) |
| 执行受限夹爪真机验收 | [`../tests/acceptance/GRIPPER_HARDWARE_ACCEPTANCE.md`](../tests/acceptance/GRIPPER_HARDWARE_ACCEPTANCE.md) |

## 接口与协议

| 主题 | 阅读 |
|---|---|
| Web Gateway、9983 和后端代理 | [`apps/WEB_GATEWAY.md`](apps/WEB_GATEWAY.md) |
| Robot Service、3000 和运动安全 | [`services/ROBOT_SERVICE_PROTOCOL.md`](services/ROBOT_SERVICE_PROTOCOL.md) |
| Skill manifest、授权与结果协议 | [`SKILL_PROTOCOL.md`](SKILL_PROTOCOL.md) |
| 资产来源、哈希和准备方式 | [`assets/ASSET_PROVENANCE.md`](assets/ASSET_PROVENANCE.md) |

## 架构与边界

- [`DIRECTORY_MAP.md`](DIRECTORY_MAP.md)：当前正式目录、运行链路和放置规则。
- [`MIGRATION_BACKLOG.md`](MIGRATION_BACKLOG.md)：来源到目标映射、迁移顺序与 History 删除门槛。
- [`VOICE_ACTION_CONTROL_CHAIN_DESIGN.md`](VOICE_ACTION_CONTROL_CHAIN_DESIGN.md)：语音与模型候选、计划、授权、监督和 Robot 执行设计。
- [`VOICE_GRIPPER_CONTROL_IMPLEMENTATION_PLAN.md`](VOICE_GRIPPER_CONTROL_IMPLEMENTATION_PLAN.md)：Phase 0–2 的逐文件、逐测试实施计划与硬件门禁。
- [`OPERATIONS.md`](OPERATIONS.md)：运行进程、端口和硬件所有权规则。
- [`../History/project-records/migration/FOUNDATION_BASELINE.md`](../History/project-records/migration/FOUNDATION_BASELINE.md)：统一前的迁移基线，仅作为历史记录。
- [`../History/project-records/implementation-plans/specs/2026-09-10-unified-platform-skills-design.md`](../History/project-records/implementation-plans/specs/2026-09-10-unified-platform-skills-design.md)：平台与 Skill 目标设计，仅作为历史记录。
- [`../History/README.md`](../History/README.md)：历史代码分类、只读规则与来源。

## 按模块阅读

- [`../apps/README.md`](../apps/README.md)：操作员应用和统一启动器。
- [`../services/README.md`](../services/README.md)：机器人、语音、视觉常驻服务。
- [`../services/model/README.md`](../services/model/README.md)：规划中的 VLA、ACT、Diffusion Policy 推理服务。
- [`../services/supervisor/README.md`](../services/supervisor/README.md)：规划中的只读执行监督服务。
- [`../drivers/README.md`](../drivers/README.md)：硬件驱动边界。
- [`../platform/README.md`](../platform/README.md)：跨服务契约与 Skill 注册。
- [`../skills/README.md`](../skills/README.md)：可发现能力及其实现状态。
- [`../skills/vision/active-view/README.md`](../skills/vision/active-view/README.md)：规划中的主动视角 Skill。
- [`../configs/README.md`](../configs/README.md)：运行 profile 与配置来源。
- [`../assets/README.md`](../assets/README.md)：可跟踪资产说明。
- [`../local/README.md`](../local/README.md)：不提交 Git 的机器本地载荷。
- [`../runtime/README.md`](../runtime/README.md)：运行状态、日志和构建产物。
- [`../tools/README.md`](../tools/README.md)：资产准备、诊断和测试工具。

## 状态词含义

- **已迁移**：正式路径、配置、启动入口和测试已经存在。
- **部分迁移**：协议或界面已存在，但执行 Worker 或闭环尚未接通。
- **待迁移**：实现仍只在 `History/` 或来源快照中，正式运行路径不会加载。
- **待实现**：当前项目中没有可复用的完整实现。

文档中的“Skill 已定义”不等于“Skill 可执行”。可执行性必须同时满足 manifest、Worker、依赖服务、设备状态和授权要求。
