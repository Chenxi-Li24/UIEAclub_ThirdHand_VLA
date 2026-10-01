# Configurations

`configs/` 保存可提交、可审查的配置来源，不保存密码、令牌或大型模型。

| 路径 | 内容 |
|---|---|
| `runtime/` | launcher profile、服务端口、启动顺序和环境变量 |
| `assets/` | SDK、模型、运行时和机器人资产清单模板 |
| `vision.yaml` | Vision Service 的相机与检测配置 |

正式 `runtime/manual-control.json` 的服务端口为：机器人 `127.0.0.1:3000`、语音与 LLM Controller `127.0.0.1:3004`、视觉 `127.0.0.1:3100`、BottleGrasp 适配入口 `127.0.0.1:8766`、局域网 Web Gateway `192.168.58.68:9983`。

该 profile 使用 `TEXT_LLM_MODEL=deepseek-v4-pro` 处理普通文本，`VISION_LLM_MODEL=deepseek-flash` 处理视觉 Skill 的图片，并通过 `VISION_STREAM_URL=http://127.0.0.1:3100/camera/xvisio/raw` 复用现有视频流。模型调用是出站 API 请求，不是新的本机监听端口；凭据不要写入仓库。

配置优先级和环境变量以各服务文档及 [`.env.example`](../.env.example) 为准。本机路径或敏感值应写入未跟踪的本地配置，不要硬编码到正式源码。
