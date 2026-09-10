# Web Gateway

## Purpose

`apps/web` 是浏览器唯一入口。它把原有 Startouch Three.js 控制页迁入统一项目，同时把硬件所有权留在 loopback Robot Service。

默认 LAN 地址：

```text
http://192.168.58.68:9983
ws://192.168.58.68:9983/ws
```

## Layout

- `public/index.html`：控制页；
- `public/css/style.css`：界面样式；
- `public/js/main.js`：机械臂模型、关节/夹爪控件、状态事件；
- `public/js/voice-control.js`：语音 UI；服务尚未迁移；
- `src/static-server.js`：静态文件和模型挂载；
- `src/robot-proxy.js`：Robot 命令白名单；
- `src/server.js`：HTTP/WS 入口与 readiness；
- `assets/robot/startouch-v3`：本地 URDF/STL，映射到 `/models/startouch-v3`。

## Routing

| 路径 | 当前行为 |
|---|---|
| `/`、`/css/*`、`/js/*` | 提供迁移后的页面 |
| `/models/*` | 从 `assets/robot` 只读提供机器人几何 |
| `/health` | 返回 Web 和依赖状态 |
| `/ws` | 与 Robot Service 建立一对一上游连接 |
| `/api/vision/*`、`/camera/*` | 当前返回 503 `service_unavailable` |

静态路径经过 URL 解码、根目录约束和文件类型处理，不能使用 `..` 离开 public 或 assets 根目录。

## Robot Proxy

网关只转发：

`connect`、`disconnect`、`status`、`servo`、`preset`、`gripper`、`software_stop`、`estop`、`ping`。

视觉、目标选择、监督、VLA 和自动夹取命令不会被发送到 Robot Service，而是返回 `service_unavailable`。Robot Service 不可达时页面仍可加载，命令返回 `robot_service_unavailable`。

## Current UI Limitations

当前页面视觉区和语音区是保留的前端界面，不代表服务已上线：

- XVisio 视频路径当前返回 503，因此画面不会更新；
- 检测框、目标选择和夹取按钮没有在线 Vision/Supervisor；
- 语音代码预留 3001/3002，但 Speech Service 尚未迁移；
- 机械臂、夹爪、实时角度和 URDF 模型可通过已迁移 Robot Service 工作。

这种“界面保留、能力失效关闭”的状态用于继续后续迁移，同时避免暗中依赖旧进程。

## Configuration

环境变量：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `WEB_HOST` | `0.0.0.0` | HTTP/WS 监听地址 |
| `WEB_PORT` | `9983` | 网关端口 |
| `ROBOT_WS_URL` | `ws://127.0.0.1:3000/ws` | Robot 上游 |
| `WEB_PUBLIC_DIR` | 项目 `apps/web/public` | 页面根目录 |
| `ROBOT_ASSETS_DIR` | 项目 `assets/robot` | 模型根目录 |
| `THIRDHAND_READY_FILE` | `runtime/run/web.ready` | launcher readiness |

生产运行应使用 `configs/runtime/manual-control.json`，不要手工让 Robot Service 对 LAN 监听。
