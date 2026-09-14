# Services

`services/` 放置可独立启动、具有明确端口和健康状态的常驻能力服务。

| 服务 | 默认端口 | 设备权限 | 当前状态 |
|---|---:|---|---|
| `robot/` | 3000 | 独占 `can0`，控制 Startouch 机械臂和夹爪 | 已迁移 |
| `speech/` | 3004 | 麦克风与音频输出，不得执行机器人命令 | 已迁移 |
| `vision/` | 3100 | 通过 `drivers/xvisio` 读取 RGB-D，不得控制机器人 | 已迁移 |

服务默认只监听 loopback，由 `apps/web` 在 9983 上统一转发。新增服务时应同时提供健康检查、readiness、配置项、关闭行为和对应测试。

Robot Service 协议见 [`../docs/services/ROBOT_SERVICE_PROTOCOL.md`](../docs/services/ROBOT_SERVICE_PROTOCOL.md)。监督、模型 Worker 和自动夹取服务仍未进入正式目录。
