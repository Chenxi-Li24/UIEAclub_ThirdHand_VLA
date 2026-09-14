# Applications

`apps/` 放置操作员直接使用的应用层入口。应用可以组合服务，但不实现设备驱动。

| 路径 | 用途 | 主要入口 |
|---|---|---|
| `launcher/` | 按 profile 启停服务、记录 PID/ready/log、检查进程所有权 | `./thirdhand`、`apps/launcher/src/cli.js` |
| `web/` | 9983 局域网页面、Three.js/URDF 展示及 Robot/Speech/Vision 代理 | `apps/web/src/server.js` |

边界：`apps/web` 不直接加载 Startouch SDK，也不直接访问 `can0`。机器人命令必须经过 Robot Service；未来 LLM 动作还必须经过计划、授权和执行层。

运行方法见 [`../docs/RUN_GUIDE.md`](../docs/RUN_GUIDE.md)，Web 接口见 [`../docs/apps/WEB_GATEWAY.md`](../docs/apps/WEB_GATEWAY.md)。
