# ThirdHand 9983 / 3004 交付版

`Thirdhand_language` 是当前已验收的 9983 网页与 3004 Voice/Language 服务的集中交付目录。它包含完整 9983 网页、三个本地 ASR 模型、3004、独立 Python 运行环境和独立 Node 运行环境。

## 系统边界

本目录负责：

- 完整 9983 网页、机械臂三维模型与现有控制交互；
- 3004 Voice/Language 服务；
- Medium、Real-time、High 三个 ASR 模型；
- ASR 模型单实例驻留与录音期间禁止切换；
- Claude 候选生成、用户确认、TTS 和向 3000 转发控制请求。

本目录不包含：

- 外部 3000 机械臂服务、Startouch SDK、CAN 和硬件驱动；
- 视觉、Lumos、XVision、3001 或 3100 服务；
- NVIDIA 驱动和 Ubuntu 系统组件；
- Claude 密钥。Claude 继续继承当前 Ubuntu 登录环境，调用方式没有改变。

## 链路

```text
浏览器
  ├─ HTTP / WebSocket -> 9983（本目录 app/）
  │                       ├─ 机械臂状态与控制 -> 外部 3000 -> CAN/机械臂
  │                       └─ Voice WebSocket -> 3004
  │                                              ├─ 本地 ASR（三选一）
  │                                              ├─ Claude（保持原调用方式）
  │                                              └─ Edge TTS
  └─ 本地加载 URDF、STL 和 Three.js 三维模型资源
```

详细链路见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，端口和接口见 [docs/INTERFACES.md](docs/INTERFACES.md)。

## 正式启动

```bash
cd /home/nieqingcao/Thirdhand_language
scripts/preflight
scripts/start
scripts/status
```

停止：

```bash
cd /home/nieqingcao/Thirdhand_language
scripts/stop
```

不要使用 `sudo` 启动，不要直接运行 `voice_bridge.py` 或 `proxy.js`，不要运行旧工程中的安装或模型下载脚本。

## Windows 访问

在 Windows PowerShell 中保持以下 SSH 隧道运行：

```powershell
ssh -N -o IdentitiesOnly=yes `
  -i "$env:USERPROFILE\.ssh\thirdhand_codex_ed25519" `
  -L 9983:127.0.0.1:9983 `
  -L 3004:127.0.0.1:3004 `
  nieqingcao@192.168.58.68
```

浏览器打开 `http://127.0.0.1:9983`。

## 三个 ASR 模型

| 页面名称 | 技术名称 | 设备 | 用途 |
|---|---|---|---|
| Medium | Whisper Small | CUDA | 默认，中英文整句识别 |
| Real-time | Paraformer CPU | CPU | 中文流式识别、降低显存占用 |
| High | Fun-ASR-Nano | CUDA | 实验模型、显存占用较高 |

服务每次启动默认加载 Medium。任何客户端正在录音时都不能切换模型；切换时旧模型先卸载，再加载新模型。

## 临时无运动验收

`config/runtime.staging.env` 使用 9984 和 3005，并关闭所有真实执行开关：

```bash
cd /home/nieqingcao/Thirdhand_language
RUNTIME_ENV_FILE="$PWD/config/runtime.staging.env" scripts/preflight \
  --voice-port 3005 --web-port 9984
RUNTIME_ENV_FILE="$PWD/config/runtime.staging.env" scripts/start
RUNTIME_ENV_FILE="$PWD/config/runtime.staging.env" scripts/status
RUNTIME_ENV_FILE="$PWD/config/runtime.staging.env" scripts/stop
```

临时验收不得触发真实机械臂运动。正式接管 9983/3004 前必须获得负责人确认；真实运动由现场人员手动验收。

## 文档导航

- [目录说明](docs/DIRECTORY_MAP.md)
- [依赖与外部条件](docs/DEPENDENCIES.md)
- [ASR 模型说明](docs/MODEL_GUIDE.md)
- [端口与接口](docs/INTERFACES.md)
- [日常操作](docs/OPERATIONS.md)
- [验收清单](docs/ACCEPTANCE.md)
- [2026-09-10 隔离联调报告](docs/VALIDATION_REPORT_2026-09-10.md)
- [故障处理](docs/TROUBLESHOOTING.md)
- [旧资源清理边界](docs/CLEANUP_BOUNDARY.md)

版本见 `VERSION`，依赖版本见 `config/versions.lock`，完整文件校验见 `MANIFEST.sha256`。
