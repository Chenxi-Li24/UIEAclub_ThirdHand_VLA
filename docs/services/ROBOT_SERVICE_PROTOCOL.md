# Robot Service Protocol

## Boundary

Robot Service 是 Startouch 机械臂和夹爪的唯一正式所有者：

- 默认真机地址：`ws://127.0.0.1:3000/ws`；
- 模拟地址：`ws://127.0.0.1:13000/ws`；
- 健康检查：`GET /health`；
- 私有执行：`ws://127.0.0.1:3000/execution`，仅供 Orchestrator 使用；
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
| `preset` | `name: "zero"` 或 `name: "home"` | 发送明确命名的零位或安全 Home 预设 |
| `gripper` | `position: 0..1` | 控制约 0..80 mm 夹爪行程 |
| `software_stop` | 无 | 请求 SDK 清理与失能 |
| `estop` | 无 | 兼容别名，语义仍是软件停止 |
| `ping` | 无 | 返回 `pong` |

### Preset definitions

| 名称 | J1-J6（度） | 用途 |
|---|---|---|
| `zero` | `[0, 0, 0, 0, 0, 0]` | 旧 Home；仅作为明确请求的零位/参考姿态，不再代表安全 Home |
| `home` | `[-0.163927, -2.611904, -4.000000, 33.058620, 0.338783, 0.185784]` | 经过 Home commissioning 的安全 Home，供网页、语音和 Bottle-pick 统一引用 |

9983 的“预设位置”区域同时显示两个按钮，并在按钮内显示角度说明：

- `zero`：`[0, 0, 0, 0, 0, 0]°`
- `home`：`[-0.164, -2.612, -4.000, 33.059, 0.339, 0.186]°`

`STARTOUCH_ZERO_DEG` 和 `STARTOUCH_HOME_DEG` 可以分别覆盖两个预设；每个变量都必须提供六个逗号分隔的有限数字。

未列出的命令返回 `unsupported_command`。Robot Service 不接受视觉、目标选择、VLA 或自动夹取命令。

## Private Execution

`/execution` 要求请求头 `x-thirdhand-execution-token`。令牌由 Launcher 写入 `runtime/run/robot-execution.token`，权限为 `0600`；浏览器和 Web Gateway 都不能读取或代理该路由。当前只接受通过 `thirdhand.execution-primitive.v1` 校验的 `gripper.set`，不接受关节或 Home 原语。

每个 `primitiveId` 只允许使用一次。Robot Service 在发送夹爪命令前重新检查连接、500 ms 状态新鲜度和 `moving:false`，并用 `request_id` 关联完成事件。只有实际夹爪反馈在目标 2% 容差内、反馈时间晚于命令、且 J1-J6 最大变化不超过 0.5°时才返回 `completed`；超时为 `uncertain`，关节偏移为 `unexpected_arm_motion`，均不重试。

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
7. 非 `preset:zero` 的意外全零目标被拒绝。

当前关节范围为 J1 ±162°、J2 -12°..201°、J3 -183°..0°、J4/J5 ±98°、J6 ±164°。最大速度为 J1-J3 300°/s、J4-J6 1000°/s；运行时默认再乘保守的 `STARTOUCH_SPEED_SCALE=0.05`。

## Bridge Protocol

Node 与 Python 通过 stdin 发送 NDJSON 命令，通过专用文件描述符 3 接收 NDJSON 事件。SDK stdout/stderr 只作为日志，不参与结构化协议解析。

`STARTOUCH_SIMULATE=1` 使用内置模拟机械臂；自动测试不得关闭该选项。真机桥在连接时要求项目本地 SDK 路径存在，并可要求 `can0` 最近有反馈。

SDK 源码目录由 `STARTOUCH_SDK_PATH` 指定；与运行时 Python ABI 匹配的扩展目录由 `STARTOUCH_MODULE_PATH` 指定。未显式设置后者时，配置优先使用 `local/generated/startouch-python/startouch_sdk/interface_py`，不存在时才回退到 SDK 的 `interface_py`。内部 `startouch_sdk` 名称是厂商动态库的资源定位契约，准备脚本只在 Git 忽略的生成目录内保留该层级。

## Safety

`software_stop`/兼容 `estop` 并不是独立硬件急停。若 2 秒内不能确认 SDK 清理，Node 会报告无法确认失能并终止桥接进程，但仍不能保证硬件已经安全断电。
