# Services

`services/` 放置可独立启动、具有明确端口和健康状态的常驻能力服务。

| 服务 | 默认端口 | 设备权限 | 当前状态 |
|---|---:|---|---|
| `robot/` | 3000 | 独占 `can0`，控制 Startouch 机械臂和夹爪 | 已迁移 |
| `speech/` | 3004 | 麦克风、音频输出及文本/视觉问答编排，不得执行机器人命令 | 已接入 LLM Controller |
| `vision/` | 3100 | 通过 `drivers/xvisio` 读取 RGB-D，不得控制机器人 | 已迁移 |

服务默认只监听 loopback，由 `apps/web` 在 9983 上统一转发。新增服务时应同时提供健康检查、readiness、配置项、关闭行为和对应测试。

`manual-control` profile 还启动 [`../skills/manipulation/bottlegrasp/`](../skills/manipulation/bottlegrasp/) 的取放适配与监督会话入口，监听 `127.0.0.1:8766`；它位于 `skills/` 而非 `services/`，默认不自行打开相机或机器人，也不表示自主夹取闭环已完成。Speech 的 Pro/Flash 均为出站 API 调用，不新增本机模型端口。Robot Service 协议见 [`../docs/services/ROBOT_SERVICE_PROTOCOL.md`](../docs/services/ROBOT_SERVICE_PROTOCOL.md)；VLA/ACT/DP Worker 和通用自主执行闭环仍待实现。
