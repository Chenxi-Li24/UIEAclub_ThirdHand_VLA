# Applications

`apps/` 放置操作员直接使用的应用层入口。应用可以组合服务，但不实现设备驱动。

| 路径 | 用途 | 主要入口 |
|---|---|---|
| `launcher/` | 按 profile 启停服务、记录 PID/ready/log、检查进程所有权 | `./thirdhand`、`apps/launcher/src/cli.js` |
| `web/` | 9983 局域网页面、Three.js/URDF 展示及 Robot/Speech/Vision/BottleGrasp 代理 | `apps/web/src/server.js` |
| `dummy/` | 正式 YuNet 人脸跟随、BODY 补偿、J1/J4 连续控制与关键词动作；由网页授权启停，直连 3000 | `apps/dummy/apps/run_head_body_follow.py` |
| `dummy/experiments/deployment_20260915/` | 旧网关、Mink/全臂跟随和校准实验；独立 `dummy_legacy` 包，不默认启动 | 实验目录内 `apps/` |
| `fixed_tcp_demo/` | 可选固定 TCP 演示；CLI/9983 请求 3000 唯一 SDK 所有者，不默认执行 | `apps/fixed_tcp_demo/fixed_tcp_demo.py` |

美团 1034 页面及电池业务保留在原 `worktrees/cyb_branch/meituan` 工作区；主目录不保存迁移副本。一键启动通过该工作区自己的 `meituan-web` profile 启动。

边界：`apps/web` 不直接加载 Startouch SDK，也不直接访问 `can0`。语音与文字请求经 3004 的 LLM Controller；视觉问答只读取现有 3100 视频流。机器人命令仍必须经过确认与 Robot Service；LLM 不能直接执行动作。

运行方法见 [`../docs/RUN_GUIDE.md`](../docs/RUN_GUIDE.md)，Web 接口见 [`../docs/apps/WEB_GATEWAY.md`](../docs/apps/WEB_GATEWAY.md)。
