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
| Web Gateway | 正式运行 | `192.168.58.68:9983`（局域网） |
| Startouch 机器人与夹爪 | 已迁移 | `127.0.0.1:3000`、`can0` |
| Ubuntu 语音与 LLM Controller | 已接入 | `127.0.0.1:3004`；普通文本用 `deepseek-v4-pro` |
| XVisio RGB-D 与检测 | 已迁移 | `127.0.0.1:3100` |
| `inspect-scene` 视觉问答 | 已接入，只读 | 复用 3100 原始画面；图片仅发往 `deepseek-flash` API，无新监听端口 |
| BottleGrasp 取放适配入口 | 已接入 profile；非自主抓取闭环 | `127.0.0.1:8766`；默认不自行打开相机或机器人 |
| 统一 launcher | 已迁移 | `./thirdhand` |
| 通用监督执行与自主夹取闭环 | 尚未完成 | 无独立正式端口 |
| VLA、ACT、DP Worker | 待迁移 | 无 |
| LLM 直接执行授权 | 未开放 | LLM 不能直接控制机器人 |

只有 Robot Service 可访问 `can0`；视觉问答失败不会让 Pro 接收图片或自动改用机器人执行路径。

## 常用命令

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
./thirdhand start --profile manual-control
./thirdhand status --profile manual-control
./thirdhand stop --profile manual-control
```

开发时需要保留已运行服务、只补齐缺失端口，使用：

```bash
./thirdhand ensure --profile manual-control
```

该命令只执行一次检查后退出，不会重启健康服务、后台监控、开机自启或自动连接
机械臂。Windows 与 Ubuntu 桌面快捷方式的安装和反馈规则见
[`docs/ONE_CLICK_START_CN.md`](docs/ONE_CLICK_START_CN.md)。

浏览器访问 `http://192.168.58.68:9983`。服务启动后仍需操作员在页面中显式连接机械臂；启动器不会自动使能或移动机械臂。软件停止不能替代独立硬件急停或物理断电。
