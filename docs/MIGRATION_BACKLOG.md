# Migration Backlog

本文档记录 `History/` 中仍有价值的实现应迁往何处、何时可以删除旧副本，以及迁移完成需要哪些证据。它是迁移工作的清单，不是运行配置；正式服务不得导入本文件列出的历史源码路径。

## 基本原则

1. `History/` 不能整体删除，因为其中仍包含自动夹取、视觉监督、ACT 等尚未适配的实现。
2. 未适配源码继续保留在 `History/source-snapshots/`，不要直接复制进正式目录并伪装成可运行模块。
3. 正式目录中的规划模块只放边界说明，具备实现、测试、配置和健康状态后才能加入 launcher 或 Skill Registry。
4. 只有 `services/robot` 可以访问 `can0`。LLM、Skill、模型、视觉和监督服务只能通过正式协议提交计划或调用 Robot Service。
5. 模型、SDK、checkpoint 和机器标定属于 `local/`，运行日志与构建产物属于 `runtime/`，均不提交 Git。

## History 保留与删除判断

| 历史路径 | 当前判断 | 删除前必须完成 |
|---|---|---|
| `History/source-snapshots/vision-grasp` | 保留 | 迁移深度、跟踪、目标锁定、夹取规划、监督和安全门，并完成离线与真机分级验证 |
| `History/source-snapshots/policy-act` | 保留 | ACT 推理适配器、模型清单、服务健康检查和 Skill 调用链全部进入正式结构 |
| `History/source-snapshots/language` | 待差异审计 | 确认 9983 页面、3004 服务、三档 ASR、启停脚本和测试均已被正式模块覆盖 |
| `History/source-snapshots/startouch-web-vla` | 待差异审计 | 确认 Web、Robot、URDF、夹爪和安全策略功能等价且无运行引用 |
| `History/legacy-web` | 可在验证后删除 | Web Gateway、资源加载、语音和视觉代理回归通过 |
| `History/legacy-platform` | 可优先清理 | 确认正式代码和测试不引用旧 Python 包、配置与脚本 |
| `History/retired/th-fanxy` | 可优先清理 | 确认不再需要法奥机械臂、旧相机或固定点演示作为回归依据 |
| `History/project-records` | 建议保留 | 体积较小，保留来源、设计决策和迁移证据 |

## 来源到正式目标的映射

| 能力或文件类型 | 正式目标 | 当前状态 |
|---|---|---|
| 场景描述与物体检测 Skill | `skills/vision/describe-scene`、`skills/vision/detect-objects` | 协议已存在，执行能力部分迁移 |
| 检测、跟踪、深度、点云和抓取姿态 | `services/vision/python/thirdhand_va/vision/` | 基础采集与检测已迁移，几何闭环待迁移 |
| 主动视角 | `skills/vision/active-view/` | 仅规划目录 |
| 视觉监督、目标锁定和执行中断 | `services/supervisor/`，由 `skills/vision/supervise-execution` 调用 | 仅规划目录和 Skill 协议 |
| 自动夹取工作流 | `skills/manipulation/pick-and-place/` | 协议已存在，Worker 待迁移 |
| 通用任务状态机 | `platform/task_engine/` | 仅规划目录 |
| 计划哈希和一次性授权 | `platform/authorization/` | 仅规划目录 |
| Robot 限位、工作空间、回零与底层安全策略 | `services/robot/src/policies/` | 仅规划目录；现有 `motion-policy.js` 继续生效 |
| VLA、ACT、Diffusion Policy 推理 | `services/model/{vla,act,diffusion_policy}/` | 仅规划目录 |
| 模型可发现接口 | `skills/policies/{vla,act,diffusion-policy}/` | manifest 和协议已有，Worker 待迁移 |
| LLM 规划、Skill 选择和 TaskPlan 组织 | `apps/orchestrator/` | 仅规划目录 |
| 模型权重与 checkpoint | `local/models/` | 本机资产，Git 忽略 |
| 相机与机械臂标定 | `local/calibration/` | 本机资产，Git 忽略 |
| 自动化验证 | `tests/node/`、`tests/python/`、`tests/integration/` | 随每个迁移单元补充 |

## 目标调用链

```text
Speech / Web / LLM
        |
        v
apps/orchestrator
        |
        v
Skill -> TaskPlan -> Authorization -> Task Engine
  |                                     |
  +--> Vision / Model / Supervisor      v
                                  Robot Service
                                         |
                                         v
                                       can0
```

任何模型输出都只是候选结果。物理动作必须绑定当前目标身份和场景版本，经过计划校验及用户授权，再由 Robot Service 执行。

## 建议迁移顺序

1. 为当前未提交工作建立可恢复的 Git 提交或独立备份，不推送不等于有备份。
2. 补齐 Vision 的深度有效性、稳定目标身份、三维几何和离线回放验证。
3. 迁移只读 Supervisor，使其能够报告偏差和请求中断，但不能直接发送 CAN 帧。
4. 实现 Authorization 与 Task Engine，固定计划修订、目标身份、有效期和一次性消费规则。
5. 迁移 pick-and-place Worker，通过 Robot Service 执行显式动作原语。
6. 迁移 VLA、ACT、Diffusion Policy 到 Model Service，并为每个模型建立资产清单和健康状态。
7. 实现 Orchestrator，将语音或文字请求转换为计划，并按可用性选择 Skill。
8. 对每个来源快照逐项做差异审计，通过后只删除对应子目录。

## 单个模块的完成标准

一个规划模块只有同时满足以下条件，才能从“仅脚手架”改为“已迁移”：

- 入口、配置、输入输出协议和关闭行为已经明确；
- 不从 `History/`、`/home/nieqingcao/arm` 或其他旧项目动态导入代码；
- 所需 SDK、模型和标定均由本地资产清单定位并校验；
- 离线单元测试和集成测试通过；
- 涉及硬件时，仿真、只读真机检查和授权动作验证分级完成；
- launcher profile 明确启用条件，服务提供 health/readiness；
- 文档、故障语义、回滚方法和安全边界已更新。

## 删除 History 子目录的门槛

删除任一历史子目录前必须同时满足：

1. 本文档中的来源到目标映射已经关闭，无未处理文件。
2. `rg` 或边界审计确认正式代码、配置、脚本和测试没有引用该路径。
3. 需要保留的许可证、来源、清单和哈希已迁入正式文档。
4. 功能等价测试和相关回归测试通过。
5. 当前正式实现已有可恢复的 Git 提交或外部备份。
6. 删除按子目录执行，不一次删除整个 `History/`。

## 当前禁止事项

- 不为尚不可运行的 `active-view` 创建 `manifest.yaml`；
- 不把规划服务加入 launcher profile；
- 不让 Model、Supervisor、Skill 或 Orchestrator 直接访问 `can0`；
- 不用软件停止替代独立硬件急停或物理断电；
- 不因创建了目标目录就宣称对应能力已经迁移完成。
