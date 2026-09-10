# Unified Project Directory Map

正式运行代码只能依赖本仓库中已跟踪代码，以及本仓库内经过清单校验的本地资产。它不得从 `/home/nieqingcao/arm`、`migration/sources` 或 `archive` 动态导入实现。

## 当前正式运行目录

| 路径 | 内容 | 运行职责 | Git |
|---|---|---|---|
| `thirdhand` | 一键入口 | 选择 profile，调用 launcher | 跟踪 |
| `apps/launcher` | CLI、服务配置、Supervisor、状态存储 | 启停服务、核对 PID 所有权、写日志 | 跟踪 |
| `apps/web/public` | HTML、CSS、Three.js、URDFLoader、页面逻辑 | 浏览器界面与本地三维模型 | 跟踪 |
| `apps/web/src/config.js` | Web 环境变量解析 | Web 地址、端口、资产根目录、Robot URL | 跟踪 |
| `apps/web/src/static-server.js` | 受限静态文件服务器 | 提供页面和 `/models`，阻止路径穿越 | 跟踪 |
| `apps/web/src/robot-proxy.js` | Robot WebSocket 白名单代理 | 只转发正式 Robot 命令 | 跟踪 |
| `apps/web/src/server.js` | Web Gateway 入口 | 监听 LAN 9983、健康检查和 readiness | 跟踪 |
| `services/robot/src/server.js` | Robot Service 入口 | 监听 loopback、WebSocket 协议和 readiness | 跟踪 |
| `services/robot/src/robot-controller.js` | 浏览器协议控制器 | 连接状态、反馈新鲜度、命令互斥与事件适配 | 跟踪 |
| `services/robot/src/motion-policy.js` | 纯运动策略 | 关节限位、速度时间、意外全零保护 | 跟踪 |
| `services/robot/src/startouch-bridge.js` | Node/Python 进程桥 | 启停 Python、传输 NDJSON、软件停止超时处理 | 跟踪 |
| `services/robot/src/startouch_bridge.py` | Startouch SDK 适配 | CAN 预检、SingleArm、状态采样、运动和夹爪 | 跟踪 |
| `assets/robot/README.md` | 机器人几何来源和准备说明 | 描述 Web 模型挂载 | 跟踪 |
| `assets/robot/startouch-v3` | URDF 和 STL | 页面实际加载的 Startouch 模型 | 本地存在，Git 忽略 |
| `configs/runtime` | 运行 profile | 端口、环境变量、启动顺序和启用状态 | 跟踪 |
| `configs/assets` | 本地资产清单 | 哈希、大小、许可证和平台兼容性 | 模板/机器清单跟踪；local 清单忽略 |
| `local/sdk/startouch` | Startouch SDK 完整载荷 | Robot Service 显式连接时导入 | 本地存在，Git 忽略 |
| `local/runtimes` | Node/Python 环境 | 可复现项目运行时 | 本地存在，Git 忽略 |
| `local/models` | ASR/VLA/ACT/DP 模型 | 后续服务使用 | 本地存在，Git 忽略 |
| `runtime/run` | PID、ready、状态 | 当前一次运行的所有权证据 | Git 忽略 |
| `runtime/logs` | 服务 stdout/stderr | 诊断 | Git 忽略 |
| `tools/assets` | 导入、记录和验证工具 | 显式准备本地资产，不自动下载 | 跟踪 |
| `tests/node/robot_service` | Robot Node 测试 | 协议、连接和运动策略 | 跟踪 |
| `tests/python/robot_service` | Python 桥测试 | 模拟 SDK 生命周期 | 跟踪 |
| `tests/node/web` | Web Gateway 测试 | 静态服务、代理、503 和路径安全 | 跟踪 |
| `tests/node/launcher` | 生命周期/profile 测试 | 端口、入口和进程所有权 | 跟踪 |

## 平台与后续迁移

| 路径 | 目标职责 | 当前状态 |
|---|---|---|
| `platform/contracts` | TaskPlan、Authorization、TargetRef、SkillResult 模式 | 已有基础 |
| `platform/skill_registry` | 发现 Skill 并根据服务/设备/模型发布可用性 | 已有基础 |
| `platform/task_engine` | 任务状态机 | 待实现 |
| `platform/authorization` | 计划哈希和一次性授权 | 待实现 |
| `services/vision` | 常驻 RGB-D、检测、稳定 TargetRef | 待迁移 |
| `services/speech` | 常驻 ASR/TTS | 待迁移 |
| `services/model` | VLA/ACT/DP 模型适配 | 待迁移 |
| `services/supervisor` | 只读视觉监督和中断 | 待迁移 |
| `apps/orchestrator` | LLM 计划和 Skill 调用 | 待实现 |
| `skills` | 视觉、监督、策略、夹取协议 | manifest/SKILL.md 已有，worker 待迁移 |

## 历史与来源目录

- `migration/sources`：迁移时冻结的来源快照，不是运行依赖；
- `archive`：法奥机械臂、旧 D435/Lumos 双相机、重复固定点演示和废弃视觉实现；
- `/home/nieqingcao/arm`：原项目，仅作为经批准的复制来源，不被正式代码引用。

只有 Robot Service 可以拥有 `can0`。只有未来 Vision Service 可以拥有 XVisio 相机。Skill 和 LLM 都不能直接发 CAN 帧。
