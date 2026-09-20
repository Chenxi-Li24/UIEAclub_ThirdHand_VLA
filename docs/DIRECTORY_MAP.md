# Unified Project Directory Map

本文件回答两个问题：看到一个文件时它属于哪一层，以及新增功能时应该放在哪里。正式运行代码只能依赖本仓库中已跟踪代码和经过清单校验的 `local/` 资产，不得从 `/home/nieqingcao/arm` 或 `History/` 动态导入实现。

## 顶层速查

| 分组 | 路径 | 放什么 | 不放什么 |
|---|---|---|---|
| 产品入口 | `apps/` | launcher、Web UI、面向操作员的组合应用 | 设备 SDK、模型权重 |
| 常驻能力 | `services/` | Robot、Speech、Vision 等独立服务 | 页面组件、历史副本 |
| 设备适配 | `drivers/` | XVisio 等原生设备适配和帧协议 | 目标选择、机器人动作 |
| 平台协议 | `platform/` | 跨服务契约、Skill 注册与未来任务编排 | 单一服务的私有实现 |
| 能力目录 | `skills/` | manifest、Skill 协议、Worker 入口 | 绕过授权的硬件控制 |
| 配置资产 | `configs/`、`assets/` | 可跟踪配置、清单模板、资产说明 | 密钥、大型二进制和模型 |
| 本机载荷 | `local/` | SDK、模型、运行时、标定 | 应提交 Git 的源码 |
| 运行产物 | `runtime/` | PID、ready、日志、原生构建 | 手工维护的正式配置 |
| 工程质量 | `tests/`、`tools/` | 测试、诊断、资产准备和夹具 | 生产常驻服务 |
| 知识入口 | `docs/` | 运行指南、架构、协议和迁移状态 | 代码副本 |
| 历史归档 | `History/` | 旧实现、来源快照、迁移记录 | 正式运行依赖 |
| 兼容占位 | `data/`、`logs/` | 迁移期保留的说明和占位 | 新的本机数据或日志 |

主要顶层目录各自的 `README.md` 是目录入口；全部文档从 [`INDEX.md`](INDEX.md) 查找。

## 正式运行链路

```text
thirdhand
  -> apps/launcher
       -> apps/web (0.0.0.0:9983)
       -> services/robot (127.0.0.1:3000, only CAN owner)
       -> services/speech (127.0.0.1:3004)
       -> services/vision (127.0.0.1:3100)
            -> drivers/xvisio
```

`apps/web` 负责统一浏览器入口，但不拥有设备。每个服务应可单独做健康检查，由 launcher 通过 profile 管理生命周期。

## 应用层

| 路径 | 职责 |
|---|---|
| `thirdhand` | 一键选择 profile 并调用 launcher |
| `apps/launcher/src/cli.js` | `start`、`status`、`stop` 命令入口 |
| `apps/launcher` | 服务启动顺序、PID 所有权、ready 与日志管理 |
| `apps/web/public` | HTML、CSS、Three.js、URDFLoader 和页面交互 |
| `apps/web/src/server.js` | Web Gateway、健康检查和 readiness |
| `apps/web/src/robot-proxy.js` | Robot WebSocket 命令白名单代理 |
| `apps/web/src/http-proxy.js` | Vision HTTP 白名单和流式代理 |
| `apps/web/src/vision-proxy.js` | Vision WebSocket 事件与目标选择代理 |
| `apps/web/src/websocket-proxy.js` | Speech/Vision 通用有界 WebSocket 代理 |
| `apps/dummy` | Dum-E 个性状态机、人物跟随和手势实验；手动启动，尚未接入授权执行链 |

## 服务与驱动层

| 路径 | 职责 | 权限边界 |
|---|---|---|
| `services/robot/src/server.js` | Robot Service、WebSocket 协议和 readiness | 唯一允许拥有 `can0` 的服务 |
| `services/robot/src/robot-controller.js` | 连接状态、反馈新鲜度、命令互斥和事件适配 | 所有运动必须经过安全策略 |
| `services/robot/src/motion-policy.js` | 关节限位、速度时间和意外全零保护 | 纯策略，不直接访问 SDK |
| `services/robot/src/startouch-bridge.js` | Node/Python 进程桥和软件停止超时 | 不解析浏览器 UI 状态 |
| `services/robot/src/startouch_bridge.py` | CAN 预检、SingleArm、状态采样、关节和夹爪 | 不被其他服务直接导入 |
| `services/speech/src/voice_bridge.py` | 三模型 ASR、对话和候选动作 | 候选动作不能直接执行 |
| `services/speech/src/model_paths.py` | Medium、Real-time、High 模型定位 | 只解析统一项目内模型 |
| `services/vision/src/server.js` | MJPEG、状态、目标选择和 Vision API | 无机器人控制权限 |
| `services/vision/python/camera_bridge.py` | RGB-D 采集、检测框、深度和稳定目标 ID | 不发送运动命令 |
| `drivers/xvisio` | 相机枚举、序列号、原生库和帧协议 | 仅设备适配 |

## 平台与 Skill

| 路径 | 目标职责 | 当前状态 |
|---|---|---|
| `platform/contracts` | TaskPlan、Authorization、TargetRef、SkillResult | 基础协议已存在 |
| `platform/skill_registry` | 根据服务、设备和模型状态发布 Skill 可用性 | 基础能力已存在 |
| `platform/task_engine` | 任务状态机 | 规划脚手架，尚无实现 |
| `platform/authorization` | 计划哈希和一次性授权 | 规划脚手架，尚无实现 |
| `skills/vision` | 场景描述、物体检测和执行监督协议 | 部分迁移 |
| `skills/vision/active-view` | 主动观察动作与视觉证据刷新协议 | 规划脚手架，未注册 |
| `skills/manipulation` | 受监督 pick-and-place 协议 | Worker 待迁移 |
| `skills/policies` | VLA、ACT、Diffusion Policy 适配协议 | Worker 待迁移 |
| `services/model` | VLA、ACT、Diffusion Policy 模型 Worker 服务 | 规划脚手架，尚无实现 |
| `services/supervisor` | 只读视觉监督和中断服务 | 规划脚手架，尚无实现 |
| `services/robot/src/policies` | 待拆分的 Robot 纯安全策略 | 规划脚手架；当前仍使用 `motion-policy.js` |
| `apps/orchestrator` | LLM 计划和 Skill 调用 | 规划脚手架，尚无实现 |

Skill manifest 存在只表示能力契约可被发现，不代表对应 Worker 已经可执行。
规划目录的详细迁移顺序和完成标准见 [`MIGRATION_BACKLOG.md`](MIGRATION_BACKLOG.md)。

## 配置、资产与运行数据

| 路径 | 内容 | Git 策略 |
|---|---|---|
| `configs/runtime` | profile、端口、环境变量、启动顺序 | 跟踪 |
| `configs/assets` | SDK、模型、运行时和几何资产清单模板 | 跟踪模板；机器清单按规则处理 |
| `configs/vision.yaml` | XVisio 和检测配置 | 跟踪，不放密钥 |
| `assets/robot` | 机器人几何来源和准备说明 | 说明跟踪，大型载荷忽略 |
| `local/sdk/startouch` | Startouch SDK 完整载荷 | 本地存在，Git 忽略 |
| `local/generated/startouch-python` | 与项目 Python ABI 匹配的绑定 | 本地生成，Git 忽略 |
| `local/runtimes` | Node/Python 环境 | 本地存在，Git 忽略 |
| `local/models` | ASR、视觉和可选策略模型 | 本地存在，Git 忽略 |
| `local/calibration` | 机器专属相机与机器人标定 | 本地存在，Git 忽略 |
| `runtime/run` | PID、ready 和 launcher 状态 | Git 忽略 |
| `runtime/logs` | 服务 stdout/stderr | Git 忽略 |
| `runtime/build` | XVisio 等原生构建产物 | Git 忽略 |
| `data` | 可跟踪数据结构占位 | 不放机器专属数据 |
| `logs` | 旧路径兼容占位 | 新代码不得写入 |

## 测试与工具

| 路径 | 覆盖范围 |
|---|---|
| `tests/node/launcher` | 生命周期、profile、端口和进程所有权 |
| `tests/node/web` | 静态服务、代理、503 和路径安全 |
| `tests/node/robot_service` | Robot 协议、连接和运动策略 |
| `tests/python/robot_service` | Python 桥和模拟 SDK 生命周期 |
| `tests/python/vision_service` | XVisio 帧、深度、检测与目标状态 |
| `tests/unit/platform` | 仓库布局、协议和边界规则 |
| `tests/integration` | 跨模块离线集成 |
| `tools/assets` | 资产记录、校验、导入和 Python 绑定生成 |
| `tools/diagnostics` | 设备、环境、端口和边界诊断 |
| `tools/fixtures` | 测试固定输入 |

## 历史边界

- `History/source-snapshots`：迁移时冻结的来源快照；
- `History/retired`：法奥机械臂、旧相机方案和废弃实现；
- `History/legacy-web`：旧网页；
- `History/legacy-platform`：旧平台、脚本、配置和测试；
- `History/project-records`：迁移计划与实施记录；
- `/home/nieqingcao/arm`：原项目，只能作为经批准的复制来源。

正式代码、配置、启动脚本和测试不得把上述位置加入运行时搜索路径。该规则由 [`../tests/unit/platform/test_repository_layout.py`](../tests/unit/platform/test_repository_layout.py) 和 [`../History/README.md`](../History/README.md) 共同记录与验证。

## 新文件放置规则

1. 新的浏览器交互放 `apps/web`，通用协议不要埋在页面脚本中。
2. 新的常驻能力放 `services/<name>`，并提供健康检查、readiness、关闭行为和测试。
3. 新设备接入放 `drivers/<device>`，业务识别逻辑保留在对应服务中。
4. 跨服务稳定结构放 `platform/contracts`，单服务私有结构留在服务内部。
5. 新 Skill 先定义 manifest、权限、输入输出和失败语义，再接 Worker。
6. SDK、模型和机器标定放 `local/`，运行日志与构建产物放 `runtime/`。
7. 旧实现或迁移证据放 `History/`，不得重新接入正式运行链路。
