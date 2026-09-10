# Robot Service Protocol

## Boundary

Robot Service 是 Startouch 机械臂和夹爪的唯一正式所有者：

- 默认真机地址：`ws://127.0.0.1:3000/ws`；
- 模拟地址：`ws://127.0.0.1:13000/ws`；
- 健康检查：`GET /health`；
- 只绑定 loopback，不对局域网直接开放；
- 只有该服务可以导入 Startouch SDK、构造 `SingleArm` 或访问 `can0`。

服务启动会启动 Python 桥，但不会导入 SDK 或构造机械臂对象。必须收到显式 `connect`。

## Browser Commands

所有消息均为 JSON 文本帧。

| `cmd` | 字段 | 行为 |
|---|---|---|
| `connect` | 无 | CAN 反馈预检后构造 SDK；不发送运动目标 |
| `disconnect` | 无 | 销毁 SDK 对象并失能电机 |
| `status` | 无 | 返回当前反馈；未连接时返回错误 |
| `servo` | `joints: number[6]`，单位度 | 经安全策略后发送关节运动 |
| `preset` | `name: "home"` | 唯一允许发送全零目标的入口 |
| `gripper` | `position: 0..1` | 控制约 0..80 mm 夹爪行程 |
| `software_stop` | 无 | 请求 SDK 清理与失能 |
| `estop` | 无 | 兼容别名，语义仍是软件停止 |
| `ping` | 无 | 返回 `pong` |

未列出的命令返回 `unsupported_command`。Robot Service 不接受视觉、目标选择、VLA 或自动夹取命令。

## Events

| `type` | 关键字段 | 含义 |
|---|---|---|
| `config` | `jointLimits`, `motion`, `connection` | 客户端初始配置 |
| `connection` | `connected`, `interface`, `reason` | SDK 连接变化 |
| `robot_state` | `joints`, `velocities`, `torques`, `tcpPos`, `gripperPosition` | 实时状态 |
| `motion_state` | `stateName` | `IDLE` 或 `MOVING` |
| `command_status` | `status`, `command` | accepted/complete |
| `software_stop` | `complete`, `depowered` | 软件停止确认 |
| `sdk_log` | `level`, `msg` | SDK 可见日志 |
| `error` | `code`, `msg` | 稳定错误 |
| `pong` | `ts` | 连通性响应 |

## Motion Gates

关节运动与夹爪命令必须同时满足：

1. SDK 已连接；
2. 最近 500 ms 内收到合法状态；
3. 六关节反馈完整且为有限数；
4. 当前没有另一条运动；
5. 目标通过关节限位；
6. 计算时长不超过关节最大速度；
7. 非 `preset:home` 的意外全零目标被拒绝。

当前关节范围为 J1 ±162°、J2 -12°..201°、J3 -183°..0°、J4/J5 ±98°、J6 ±164°。最大速度为 J1-J3 300°/s、J4-J6 1000°/s；运行时默认再乘保守的 `STARTOUCH_SPEED_SCALE=0.05`。

## Bridge Protocol

Node 与 Python 通过 stdin 发送 NDJSON 命令，通过专用文件描述符 3 接收 NDJSON 事件。SDK stdout/stderr 只作为日志，不参与结构化协议解析。

`STARTOUCH_SIMULATE=1` 使用内置模拟机械臂；自动测试不得关闭该选项。真机桥在连接时要求项目本地 SDK 路径存在，并可要求 `can0` 最近有反馈。

## Safety

`software_stop`/兼容 `estop` 并不是独立硬件急停。若 2 秒内不能确认 SDK 清理，Node 会报告无法确认失能并终止桥接进程，但仍不能保证硬件已经安全断电。
