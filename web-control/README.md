# ThirdHand Startouch Web Control

## 快速启动 / Quick Start

```powershell
# Windows PowerShell（开发模式，不控制机械臂）
cd web-control\server
npm install
$env:STARTOUCH_SIMULATE = "1"
npm start
```

浏览器打开 `http://127.0.0.1:3000/`。

> 语音 AI 需要 Ubuntu PC 上运行 `voice_bridge.py --host 0.0.0.0 --port 3001`。
> 详见下方"语音和文字 AI"一节。

---

在 Ubuntu 上通过网页直接控制 Startouch FastTouchV3 机械臂。控制链路不使用法奥
SDK，也不经过 ESP32-P4 或其他控制开发板。

这是当前仓库中已经过真机联调的直接控制入口，默认端口为 `3000`。仓库根目录下
Python VLA 框架自带的 FastAPI 控制台使用端口 `8000`，两者用途不同。

## 控制链路

```text
浏览器
  -> WebSocket /ws
  -> Node.js server/proxy.js
  -> JSON Lines
  -> LumosTouch Python + startouch_sdk
  -> SocketCAN can0
  -> Startouch 机械臂
```

`server/startouch_bridge.py` 负责 SDK 状态读取、CAN 预检、限位校验、轨迹和夹爪
控制。`startouch_sdk` 是外部依赖，不包含在本仓库中。

## 语音和文字 AI / Voice & Text AI

网页控制台提供麦克风和文字对话入口：

```text
浏览器麦克风或文字
  → Voice Protocol v1 WebSocket
  → voice_bridge.py（Ubuntu PC）
  → WhisperASR（仅语音）→ RTX 5060 GPU · CUDA float16
  → ClaudeAgent → DeepSeek v4-pro
  → 最终转写、AI 回复和候选动作
  → 网页显示与本地 3D 预览
```

Voice Bridge 与 Startouch 真实控制链隔离。它不导入 `RobotExecutor`，不连接
机器人 `/ws` 控制代理，也不会将 AI 候选动作直接发送给机械臂。

### 启动语音后端

```bash
cd ~/thirdhand-voice
conda activate voice-bridge
python voice_bridge.py --host 0.0.0.0 --port 3001
```

模型文件在 HuggingFace 上首次下载约 2 GB（`Systran/faster-whisper-small`）。
国内网络慢时可从已有设备复制缓存：

```bash
scp -r <已有缓存的主机>@<IP>:~/.cache/huggingface ~/.cache/
```

端口 `3001` 上启动后，`WhisperASR` 自动检测 CUDA 并启用 GPU 推理。

### 语音模块文件

```text
web-control/voice-bridge/
├── voice_agent.py           # WhisperASR + ClaudeAgent + 全部语音类
├── voice_bridge.py           # WebSocket 桥接服务
├── test_voice_bridge.py      # 28 项协议与安全测试
├── requirements.txt          # 完整 Python 依赖
├── requirements-voice-bridge.txt  # 最小依赖（仅测试用）
└── README.md                 # 部署与测试说明
```

相关文档：

- [Voice Protocol v1](docs/voice-protocol-v1.md)
- [本次 Voice Bridge 更新日志](docs/voice-bridge-update-2026-07-30.md)
- [Voice Bridge 部署与测试](voice-bridge/README.md)

## 支持环境

| 系统 | 状态 | Python | Node.js |
|---|---|---|---|
| Ubuntu 20.04 x86_64 | 已真机验证 | LumosTouch Python 3.10 | 18+ |
| Ubuntu 22.04 x86_64 | 已准备安装流程，待真机回归 | Python 3.10 | 18+ |

SDK 自带的 Python 扩展和 `libstartouch.so` 必须与系统架构、Python ABI 匹配。
升级 Ubuntu 前应先在 `STARTOUCH_DRY_RUN=1` 模式验证 SDK 导入，再连接真机。

## 安装

推荐目录：

```text
~/arm/
├── startouch_sdk/
└── UIEAclub_ThirdHand_VLA/
```

克隆并安装网页依赖：

```bash
cd ~/arm
git clone https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git
cd UIEAclub_ThirdHand_VLA
cp web-control/.env.example web-control/.env
web-control/scripts/setup_ubuntu.sh
```

安装脚本不会修改系统软件包。它会检查 Ubuntu 版本、Node.js、npm、`ip`、
LumosTouch Python 和 Startouch SDK，然后通过 `npm ci` 安装锁定依赖。

若 Node.js 低于 18，请先通过 NodeSource 或 nvm 安装当前 LTS 版本。Ubuntu 20.04
和 22.04 系统仓库中的 Node.js 版本可能过旧。

## CAN 配置

每次重启后确认 CAN 接口存在并处于 `UP`：

```bash
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
ip -details link show can0
```

机械臂电机不是持续广播模式，空闲时 `candump can0` 没有输出不一定代表故障。
网页连接前会使用只读 `0xCC` 查询验证 J1-J6 反馈。

## 启动

### 开发模式（仅网页，不控制机械臂）

```powershell
cd web-control\server
npm install
$env:STARTOUCH_SIMULATE = "1"
$env:WEB_HOST = "127.0.0.1"
npm start
```

浏览器打开 `http://127.0.0.1:3000/`。语音面板填写 PC 的 Bridge 地址
`ws://<PC_IP>:3001/v1/voice` 后点击重连。

### 真机模式（Ubuntu，连接机械臂）

```bash
cd ~/arm/UIEAclub_ThirdHand_VLA
web-control/scripts/start_ubuntu.sh
```

局域网浏览器打开：

```text
http://<Ubuntu局域网IP>:3000
```

页面加载不会自动使能机械臂。点击“连接”后才构造 `SingleArm`。

## 环境变量

在 `web-control/.env` 中设置覆盖项。默认值适用于推荐目录。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `STARTOUCH_PYTHON` | `~/miniconda3/envs/LumosTouch/bin/python` | SDK Python |
| `STARTOUCH_SDK_PATH` | `~/arm/startouch_sdk` | SDK 根目录 |
| `STARTOUCH_CAN_INTERFACE` | `can0` | CAN 接口 |
| `STARTOUCH_GRIPPER` | `1` | 启用夹爪 |
| `STARTOUCH_SPEED_SCALE` | `0.05` | 关节最大速度使用比例 |
| `STARTOUCH_REQUIRE_CAN_RX` | `1` | 启用 CAN 预检和运行期反馈检查 |
| `STARTOUCH_CAN_RX_STALE_SEC` | `1` | CAN 反馈停止后的断开时间 |
| `STARTOUCH_INIT_CAN_MATCH_DEG` | `5` | SDK 初始状态与 CAN 反馈允许偏差 |
| `STARTOUCH_GRIPPER_MAX_DISTANCE_M` | `0.08` | TypeLJ 最大开度 |
| `STARTOUCH_GRIPPER_KP` | `8` | 夹爪 MIT 位置增益 |
| `STARTOUCH_GRIPPER_KD` | `0.1` | 夹爪 MIT 阻尼增益 |
| `STARTOUCH_DRY_RUN` | `0` | 导入真实 SDK 但不控制硬件 |
| `STARTOUCH_SIMULATE` | `0` | 不导入 SDK，使用内置模拟机械臂 |
| `WEB_HOST` | `0.0.0.0` | Web 监听地址 |
| `WEB_PORT` | `3000` | Web 端口 |

模拟运行：

```bash
STARTOUCH_SIMULATE=1 web-control/scripts/setup_ubuntu.sh
STARTOUCH_SIMULATE=1 web-control/scripts/start_ubuntu.sh
```

## 控制与模型

- 页面加载 `web/models/startouch-v3/FastTouchV3.SLDASM.urdf` 和 STL 网格。
- 关节限位：J1 `±162°`、J2 `-12° ~ 201°`、J3 `-183° ~ 0°`、
  J4/J5 `±98°`、J6 `±164°`。
- 最大速度：J1-J3 `300°/s`，J4-J6 `1000°/s`；默认仅使用 `5%`。
- 连接时必须取得连续稳定状态，并拒绝 SDK 的瞬时全零缓存。
- 普通发送会阻止意外的六轴全零目标；回零只能使用明确的回零按钮。
- 同一 `can0` 只允许一个网页控制进程持有控制锁。
- 夹爪目标和实时反馈独立显示；打开/闭合按钮会立即发送命令。

## 安全

“软件停止”会调用 SDK `cleanup()` 并请求电机失能，但它不是硬件急停。它依赖
浏览器、网络、进程、操作系统和 CAN 总线正常工作，也没有安全继电器或双通道
诊断。现场必须保留独立、可触达、能够切断驱动使能或动力电源的硬件急停装置。

首次真机运行应保持低速、清空机械臂和夹爪工作区，并逐轴确认方向、零位和限位。
