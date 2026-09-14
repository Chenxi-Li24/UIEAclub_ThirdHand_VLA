# ThirdHand VLA

ThirdHand VLA 是面向 Startouch 六轴机械臂的统一网页控制、语音、RGB-D 视觉和 VLA 平台。仓库采用单仓多服务结构，正式代码、机器本地资产、运行产物与历史实现彼此隔离。

## 从这里开始

| 需求 | 文档 |
|---|---|
| 启动、停止和排障 | [`docs/RUN_GUIDE.md`](docs/RUN_GUIDE.md) |
| 浏览全部文档 | [`docs/INDEX.md`](docs/INDEX.md) |
| 理解目录职责 | [`docs/DIRECTORY_MAP.md`](docs/DIRECTORY_MAP.md) |
| 接入网页网关 | [`docs/apps/WEB_GATEWAY.md`](docs/apps/WEB_GATEWAY.md) |
| 查看机器人协议与安全边界 | [`docs/services/ROBOT_SERVICE_PROTOCOL.md`](docs/services/ROBOT_SERVICE_PROTOCOL.md) |
| 查看 Skill 协议 | [`docs/SKILL_PROTOCOL.md`](docs/SKILL_PROTOCOL.md) |
| 准备本地 SDK、模型和运行时 | [`local/README.md`](local/README.md) |
| 查找旧实现 | [`History/README.md`](History/README.md) |

## 目录分组

```text
UIEAclub_ThirdHand_VLA/
|-- apps/       # 操作员直接使用的应用：launcher、web
|-- services/   # 常驻能力服务：robot、speech、vision
|-- drivers/    # 设备驱动适配：XVisio
|-- platform/   # 跨服务协议与 Skill 注册
|-- skills/     # 可发现能力的 manifest、协议和入口
|-- configs/    # 可跟踪的运行配置和资产清单模板
|-- assets/     # 可跟踪的资产说明；大型载荷由准备脚本导入
|-- local/      # 本机 SDK、模型、运行时与标定，不提交 Git
|-- runtime/    # PID、ready、日志和构建产物，不提交 Git
|-- tests/      # 单元、集成、Node 与 Python 测试
|-- tools/      # 资产准备、诊断和测试夹具
|-- docs/       # 文档入口、架构、协议和运行指南
|-- History/    # 旧网页、旧平台、来源快照和迁移记录
|-- data/       # 可跟踪数据占位；本机标定放 local/calibration
|-- logs/       # 兼容占位；新日志统一写入 runtime/logs
`-- thirdhand   # 一键启动、状态和停止入口
```

每个主要顶层目录都有自己的 `README.md`，用于说明用途、边界、入口和当前状态。完整文件级映射见 [`docs/DIRECTORY_MAP.md`](docs/DIRECTORY_MAP.md)。

## 当前能力

已迁移并可独立运行：

- `apps/web`：9983 局域网页面及机器人、语音、视觉代理；
- `services/robot`：3000 Startouch SDK、CAN、关节和夹爪控制；
- `services/speech`：3004 Ubuntu 本地三档 ASR、对话和候选动作；
- `services/vision` 与 `drivers/xvisio`：3100 XVisio RGB-D、检测画面和目标选择；
- `apps/launcher`：服务生命周期、PID 所有权、日志和运行 profile；
- `platform/contracts` 与 `platform/skill_registry`：Skill 协议和可用性发现；
- 项目本地 SDK、模型、运行时清单，以及 Startouch URDF/STL 资产准备工具。

尚未完成：监督执行服务、LLM 编排器、VLA/ACT/DP Worker、主动视角和自动夹取闭环。`skills/` 中对应 manifest 表示协议已定义，不代表执行 Worker 已可用。

## 运行架构

```text
Windows browser
    |
    | http/ws://192.168.58.68:9983
    v
apps/web (Web Gateway)
    |-- ws://127.0.0.1:3000/ws --> services/robot --> Startouch SDK --> can0
    |-- http/ws://127.0.0.1:3004 --> services/speech
    `-- http/ws://127.0.0.1:3100 --> services/vision --> drivers/xvisio
```

只有 Robot Service 可以拥有 `can0`。Speech、Vision、Skill 和未来 LLM 编排器都不能直接发送 CAN 帧。

## 快速启动

安全模拟模式：

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
./thirdhand start --profile manual-control-simulation
./thirdhand status --profile manual-control-simulation
./thirdhand stop --profile manual-control-simulation
```

真机模式仅在机械臂周围安全、独立硬件急停可触达、`can0` 正常时使用：

```bash
./thirdhand start --profile manual-control
# 浏览器打开 http://192.168.58.68:9983，并由操作员显式点击“连接”
./thirdhand stop --profile manual-control
```

启动服务不会自动连接 SDK、使能电机、回零或运动。软件停止依赖网页、网络、进程、操作系统和 CAN，不能替代独立硬件急停或物理断电。

当前分支 `refactor/unified-platform-foundation` 保持本地，不推送、不合并。
