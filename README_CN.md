# ThirdHand VLA 中文入口

本仓库是 Startouch 六轴机械臂的统一网页控制、语音、RGB-D 视觉和 VLA 平台。正式运行代码只位于 `apps/`、`services/`、`drivers/`、`platform/` 和 `skills/`；旧实现和来源快照统一保存在 `History/`，不会被启动器执行。

## 文档导航

- 完整文档索引：[`docs/INDEX.md`](docs/INDEX.md)
- 启动与排障：[`docs/RUN_GUIDE.md`](docs/RUN_GUIDE.md)
- 目录职责：[`docs/DIRECTORY_MAP.md`](docs/DIRECTORY_MAP.md)
- 机器人协议：[`docs/services/ROBOT_SERVICE_PROTOCOL.md`](docs/services/ROBOT_SERVICE_PROTOCOL.md)
- Skill 协议：[`docs/SKILL_PROTOCOL.md`](docs/SKILL_PROTOCOL.md)
- 本地 SDK、模型与环境：[`local/README.md`](local/README.md)
- 历史文件：[`History/README.md`](History/README.md)

## 当前状态

| 模块 | 状态 | 默认端口或设备 |
|---|---|---|
| Web Gateway | 已迁移 | `0.0.0.0:9983` |
| Startouch 机器人与夹爪 | 已迁移 | `127.0.0.1:3000`、`can0` |
| Ubuntu 本地语音 | 已迁移 | `127.0.0.1:3004` |
| XVisio RGB-D 与检测 | 已迁移 | `127.0.0.1:3100` |
| 统一 launcher | 已迁移 | `./thirdhand` |
| 监督执行与自动夹取 | 待迁移 | 无 |
| VLA、ACT、DP Worker | 待迁移 | 无 |
| LLM 编排与一次性授权 | 待实现 | 无 |

## 常用命令

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
./thirdhand start --profile manual-control
./thirdhand status --profile manual-control
./thirdhand stop --profile manual-control
```

浏览器访问 `http://192.168.58.68:9983`。服务启动后仍需操作员在页面中显式连接机械臂；启动器不会自动使能或移动机械臂。软件停止不能替代独立硬件急停或物理断电。
