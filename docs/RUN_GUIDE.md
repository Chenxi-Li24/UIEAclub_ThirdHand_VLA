# ThirdHand 运行指南

适用目录：`/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA`

当前分支：`refactor/unified-platform-foundation`

## 1. 当前可运行范围

已可运行：

- Startouch 网页控制与三维 URDF 模型；
- 独立 Robot Service；
- 关节、预设位、夹爪、状态读取和软件停止；
- XVisio RGB-D 原始画面、深度画面、Grounded-SAM 检测框和稳定目标选择；
- 正式 Ubuntu 本地语音服务，包含 Medium、Real-time、High 三个 ASR 模型；
- 语音文字对话和候选动作预览，默认不向机械臂执行候选动作；
- 模拟模式的一键启动、状态检查和关闭。

尚不可运行：
- 受监督视觉夹取的运动执行；
- VLA、ACT、Diffusion Policy、主动视角和自动夹取。

## 2. 登录并进入项目

Windows PowerShell 或 VS Code 终端：

```powershell
ssh nieqingcao@192.168.58.68
```

Ubuntu：

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
git branch --show-current
git status --short --branch
```

## 3. 模拟模式

启动：

```bash
./thirdhand start --profile manual-control-simulation
```

访问：

- 控制页面：`http://192.168.58.68:9983`
- Web 健康检查：`http://192.168.58.68:9983/health`
- Robot Service：`127.0.0.1:13000`，只允许 Ubuntu 本机访问。

页面打开后点击“连接”，连接的是模拟机械臂。状态应显示六个关节，模型应从
`/models/startouch-v3/FastTouchV3.SLDASM.urdf` 加载。

查询与停止：

```bash
./thirdhand status --profile manual-control-simulation
./thirdhand stop --profile manual-control-simulation
```

模拟 profile 不打开 `can0`，可用于网页、协议、模型加载和生命周期验收。

## 4. 真机模式

### 4.1 启动前检查

必须满足：

- 机械臂周围无人员和障碍物；
- 独立硬件急停或物理断电手段可立即触达；
- Startouch SDK 已位于 `local/sdk/startouch`；
- 项目 Python 运行时已位于 `local/runtimes/python`，或当前 `python3` 可运行 SDK；
- `can0` 已配置为 1 Mbit/s，并能收到机械臂反馈；
- 3000 未被旧 `node proxy.js` 占用。

只读检查：

```bash
ip -details link show can0
ss -ltnp | grep -E ':(3000|9983)\b' || true
./thirdhand doctor --profile manual-control
```

需要配置 CAN 时：

```bash
sudo ip link set can0 down
sudo ip link set can0 up type can bitrate 1000000
```

### 4.2 准备 Startouch Python 模块

SDK 内的二进制扩展必须匹配项目 Python 版本。首次导入 SDK、替换 Python 运行时或切换 Ubuntu 版本后执行：

```bash
/home/nieqingcao/miniconda3/bin/python tools/assets/build_startouch_python.py \
  --python local/runtimes/python/bin/python
```

脚本在临时目录编译并以 `dry_run` 构造 `SingleArm` 验证资源加载，产物写入 `local/generated/startouch-python`；不会修改 `local/sdk/startouch`。执行脚本的 Python 需要提供 pybind11 2.10 或更高版本。
生成包内部保留厂商库硬编码要求的 `startouch_sdk/src/config` 层级；Robot Service 实际加载 `local/generated/startouch-python/startouch_sdk/interface_py`。

### 4.3 启动

```bash
./thirdhand start --profile manual-control
```

此时：

- Web 监听 `192.168.58.68:9983`；
- Robot Service 只监听 `127.0.0.1:3000`；
- Speech Service 只监听 `127.0.0.1:3004`；
- Vision Service 只监听 `127.0.0.1:3100`；
- Python 桥已就绪，但不会构造 `SingleArm`；
- 电机不会被服务启动动作使能。

打开 `http://192.168.58.68:9983`，确认真机环境安全后再点击“连接”。点击连接后 Robot Service 才检查 CAN 反馈并构造 `SingleArm`，SDK 会使能电机，但不会自动发送回零、关节、笛卡尔或夹爪目标。

### 4.4 停止

先在页面停止运动并断开，再执行：

```bash
./thirdhand stop --profile manual-control
```

检查残留：

```bash
ss -ltnp | grep -E '192\.168\.58\.68:9983|127\.0\.0\.1:3000' || true
pgrep -af 'services/robot/src/server.js|apps/web/src/server.js|startouch_bridge.py|node proxy.js' || true
```

## 5. 运动安全规则

关节范围：

| 关节 | 最小角度 | 最大角度 | 最大速度 |
|---|---:|---:|---:|
| J1 | -162° | 162° | 300°/s |
| J2 | -12° | 201° | 300°/s |
| J3 | -183° | 0° | 300°/s |
| J4 | -98° | 98° | 1000°/s |
| J5 | -98° | 98° | 1000°/s |
| J6 | -164° | 164° | 1000°/s |

运动命令还要求：

- SDK 已连接；
- 最近 500 ms 内有合法六关节反馈；
- 前一个运动已结束；
- 所有目标为有限数值且在限位内；
- 全零目标只能通过显式 `preset: home` 发送；
- 网页连接本身不会产生运动命令。

夹爪输入为 `0.0..1.0`，SDK 映射为约 0..80 mm 行程；当前 DM4310 机构按约 90° 电机总转角由 SDK 完成映射。

## 6. 日志和状态

```bash
cat runtime/run/state.json
tail -n 100 runtime/logs/robot.stdout.log
tail -n 100 runtime/logs/robot.stderr.log
tail -n 100 runtime/logs/speech.stdout.log
tail -n 100 runtime/logs/speech.stderr.log
tail -n 100 runtime/logs/vision.stdout.log
tail -n 100 runtime/logs/vision.stderr.log
tail -n 100 runtime/logs/web.stdout.log
tail -n 100 runtime/logs/web.stderr.log
```

启动器只停止它能通过 PID、Linux 进程启动标记和命令哈希确认归属的进程。

## 7. 本地资产

URDF/STL 本地路径：

```text
assets/robot/startouch-v3
```

校验并从旧副本准备：

```bash
PYTHONPATH=. python3 tools/assets/prepare_ubuntu_assets.py --manifest configs/assets/ubuntu20.manifest.json

PYTHONPATH=. python3 tools/assets/prepare_robot_assets.py \
  --source /path/to/startouch-v3 \
  --manifest configs/assets/ubuntu20.manifest.json
```

SDK、模型、Python/Node 运行时和机器人几何都保留在 Ubuntu 统一目录中。Git 仅提交清单、哈希、来源说明和准备脚本，不提交这些本地载荷。

## 8. 自动化验证

```bash
npm test --workspace services/robot
npm test --workspace apps/web
node --test tests/node/vision_service/*.test.js
PYTHONPATH=src python3 -m pytest -q tests/python/speech_service tests/python/vision_service
node --test tests/node/launcher/*.test.js
PYTHONPATH=src python3 -m pytest -q tests/python/robot_service/test_bridge_simulation.py
PYTHONPATH=src:. python3 -m pytest -q tests/unit/platform tests/integration/test_simulated_lifecycle.py
PYTHONPATH=src:. python3 tools/diagnostics/audit_boundaries.py --root . --json
git diff --check
```

所有自动化机械臂测试都使用模拟模式。真机运动验收需要针对当次测试单独确认。

## 9. 端口所有权

| 地址 | 所有者 | 说明 |
|---|---|---|
| `192.168.58.68:9983` | Web Gateway | 局域网页面和浏览器 WebSocket |
| `127.0.0.1:3000` | Robot Service | 真机 Startouch 服务 |
| `127.0.0.1:13000` | Robot Service | 模拟 profile |
| `127.0.0.1:3100` | Vision Service | XVisio 原始/识别/深度流和目标选择 |
| `127.0.0.1:3004` | Speech Service | 正式本地 ASR、对话和候选动作 |

本机已有另一个程序只在 Tailscale 地址 `100.85.63.78:9983` 监听；已验证它可与本项目绑定的 LAN 地址 `192.168.58.68:9983` 共存。

## 10. 旧服务

旧 `node proxy.js` 已停止。不要同时运行旧服务与新 Robot Service，它们会竞争 `can0` 或 3000。旧目录只用于来源追溯和显式回退，不是新项目运行依赖。

软件停止不能替代独立硬件急停。
