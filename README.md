# ThirdHand VLA

ThirdHand 是面向 Startouch 六轴机械臂的统一控制与 VLA 平台。本分支正在把已验证的网页控制、机械臂、视觉、语音和策略能力从多个旧目录迁入一个可审计、可一键启停的项目。

当前已正式迁移：

- `apps/web`：现有 Three.js/URDF 控制页面和 LAN Web Gateway；
- `services/robot`：Startouch SDK、夹爪、CAN 状态和运动安全策略；
- `apps/launcher`：服务生命周期、PID 所有权、日志和运行 profile；
- `platform/contracts`、`platform/skill_registry`：Skill 协议和可用性发现；
- 项目本地 SDK、模型与运行时清单，以及 Startouch URDF/STL 资产准备脚本。

视觉、语音、VLA/ACT/DP、主动视角和自动夹取仍在后续迁移阶段。网页保留相关控件，但网关会对未迁移能力返回明确的 `service_unavailable`，不会偷偷调用旧项目。

## 当前架构

```text
Windows browser
    |
    | http/ws://192.168.58.68:9983
    v
apps/web (Web Gateway)
    |
    | ws://127.0.0.1:3000/ws
    v
services/robot (only CAN owner)
    |
    v
project-local Startouch SDK -> can0 -> arm and gripper
```

启动服务不会连接 SDK、使能电机、回零或运动。只有网页上的显式“连接”命令才初始化 Startouch SDK。所有关节运动还要通过限位、速度、实时状态、运动互斥和意外全零目标检查。

## 快速验证

安全模拟模式：

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
./thirdhand start --profile manual-control-simulation
# 浏览器打开 http://192.168.58.68:9983
./thirdhand status --profile manual-control-simulation
./thirdhand stop --profile manual-control-simulation
```

真机模式仅在机械臂周围安全、独立硬件急停可触达、`can0` 正常时使用：

```bash
./thirdhand start --profile manual-control
# 打开页面后，仍需人工点击“连接”
./thirdhand stop --profile manual-control
```

软件停止依赖网页、网络、进程、操作系统和 CAN，不能替代独立硬件急停或物理断电。

详细说明：

- `docs/RUN_GUIDE.md`
- `docs/DIRECTORY_MAP.md`
- `docs/apps/WEB_GATEWAY.md`
- `docs/services/ROBOT_SERVICE_PROTOCOL.md`
- `docs/SKILL_PROTOCOL.md`

当前分支 `refactor/unified-platform-foundation` 保持本地，不推送、不合并。
