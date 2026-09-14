# Configurations

`configs/` 保存可提交、可审查的配置来源，不保存密码、令牌或大型模型。

| 路径 | 内容 |
|---|---|
| `runtime/` | launcher profile、服务端口、启动顺序和环境变量 |
| `assets/` | SDK、模型、运行时和机器人资产清单模板 |
| `vision.yaml` | Vision Service 的相机与检测配置 |

配置优先级和环境变量以各服务文档及 [`.env.example`](../.env.example) 为准。本机路径或敏感值应写入未跟踪的本地配置，不要硬编码到正式源码。
