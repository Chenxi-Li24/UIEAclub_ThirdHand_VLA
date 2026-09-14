# Web Gateway

## Purpose

`apps/web` 是浏览器唯一入口。它把原有 Startouch Three.js 控制页迁入统一项目，同时把硬件所有权留在 loopback Robot Service。

默认 LAN 地址：

```text
http://192.168.58.68:9983
ws://192.168.58.68:9983/ws
ws://192.168.58.68:9983/plan
```

## Layout

- `public/index.html`：控制页；
- `public/css/style.css`：界面样式；
- `public/js/main.js`：机械臂模型、关节/夹爪控件、状态事件；
- `public/js/voice-control.js`：正式语音/文字 UI 与计划确认状态；
- `public/js/plan-channel.mjs`：候选归一化、精确计划授权和一次性确认保护；
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
| `/voice` | 代理正式 Ubuntu Speech Service，要求 `thirdhand.voice.v1` |
| `/vision`、`/api/vision/*`、`/camera/*` | 代理 Vision Service 的消息、状态与 RGB-D 画面 |
| `/plan` | 代理 Orchestrator，要求 `thirdhand.plan.v1` |

静态路径经过 URL 解码、根目录约束和文件类型处理，不能使用 `..` 离开 public 或 assets 根目录。

## Robot Proxy

网关只转发：

`connect`、`disconnect`、`status`、`servo`、`preset`、`gripper`、`software_stop`、`estop`、`ping`。

视觉、目标选择、监督、VLA 和自动夹取命令不会被发送到 Robot Service，而是返回 `service_unavailable`。Robot Service 不可达时页面仍可加载，命令返回 `robot_service_unavailable`。

## Current UI Limitations

XVisio 实时画面、检测框和稳定目标选择已迁移，但 RGB-D 目标到机械臂基座的标定、Supervisor 和夹取执行尚未迁移。语音/文字只有夹爪打开与闭合可进入 `/plan`；关节、Home、软件停止、目标夹取、VLA、ACT、DP 与主动视角继续失效关闭。当前在线 9983 服务尚未切换到本次实现，切换前页面仍显示旧行为。

## Configuration

环境变量：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `WEB_HOST` | `0.0.0.0` | HTTP/WS 监听地址 |
| `WEB_PORT` | `9983` | 网关端口 |
| `ROBOT_WS_URL` | `ws://127.0.0.1:3000/ws` | Robot 上游 |
| `ORCHESTRATOR_WS_URL` | `ws://127.0.0.1:3200/plan` | Plan 上游 |
| `VOICE_WS_URL` | `ws://127.0.0.1:3004/v1/voice` | Speech 上游 |
| `VISION_HTTP_URL` / `VISION_WS_URL` | `127.0.0.1:3100` | Vision 上游 |
| `WEB_PUBLIC_DIR` | 项目 `apps/web/public` | 页面根目录 |
| `ROBOT_ASSETS_DIR` | 项目 `assets/robot` | 模型根目录 |
| `THIRDHAND_READY_FILE` | `runtime/run/web.ready` | launcher readiness |

生产运行应使用 `configs/runtime/manual-control.json`，不要手工让 Robot Service 对 LAN 监听。
