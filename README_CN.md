# ThirdHand VLA 桌面机械臂系统

ThirdHand VLA 面向 Lumos Touch R1 与 Lumos Ego 相机，整合本地视觉感知、受安全约束
的机械臂控制、可选云端 VLA 推理，以及浏览器操作界面。

## 仓库结构

| 路径 | 职责 |
| --- | --- |
| `src/uiea_thirdhand_vla/` | 可安装的 Python VLA 应用与 FastAPI 控制台 |
| `web-control/` | 独立 Startouch SDK 桥接、相机服务与操作界面 |
| `configs/` | 可移植的机械臂、相机、任务与视觉配置 |
| `scripts/` | 标定、部署、演示与验证脚本 |
| `tests/` | 可离线运行的应用及工作流测试 |
| `docs/` | 架构、安装、API、安全和研究记录 |

组件边界和数据流见 [docs/architecture.md](docs/architecture.md)。

## 快速开始

需要 Python 3.10 或更高版本。

```bash
git clone https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA.git
cd UIEAclub_ThirdHand_VLA
python -m venv .venv
. .venv/bin/activate
pip install -e ".[core]"
cp .env.example .env
python -m uiea_thirdhand_vla
```

浏览器打开 `http://localhost:8000`。

## Startouch 真机网页控制

`web-control/` 是独立部署的真机控制服务，通过 Startouch SDK 与 `can0` 控制机械臂。
启用运动前，请阅读 [web-control/README.md](web-control/README.md) 并确认硬件急停可用。

```bash
cp web-control/.env.example web-control/.env
web-control/scripts/setup_ubuntu.sh
web-control/scripts/start_ubuntu.sh
```

浏览器打开 `http://<机械臂主机>:3000`。界面代理 Startouch 桥接和 D435 视频；启用
Lumos HTTP 视频服务后，其默认端口为 `3001`。

## 固定 A/B 点抓放演示

固定点演示使用独立的本机控制页面。运动前会检查分支、`can0`、点位、关节限位、
速度、日志目录以及竞争控制进程。

```bash
bash scripts/demo_fixed_pick_place.sh
# 或打开本机控制页面：
bash scripts/open_fixed_pick_place_control.sh
```

打开 `http://127.0.0.1:8766`。不得与其他 CAN 控制程序同时运行。操作和安全细节见
[web-control/FIXED_PICK_PLACE.md](web-control/FIXED_PICK_PLACE.md)。

## 服务端口

| 端口 | 默认绑定 | 服务 |
| --- | --- | --- |
| `8000` | `0.0.0.0` | Python VLA FastAPI 控制台 |
| `3000` | `0.0.0.0` | Startouch 代理与浏览器界面 |
| `3001` | `0.0.0.0` | Lumos 相机 HTTP/MJPEG 服务 |
| `8766` | `127.0.0.1` | 固定点演示控制页面 |

可通过对应 YAML 或环境变量修改端口。

## 模型与运行数据

下载的 `*.pt`、`*.onnx` 权重、日志、PID、采集帧和点位备份均属于本机运行产物，
不会提交到 Git。模型配置方法见 [docs/model_assets.md](docs/model_assets.md)。

## 开发验证

```bash
pip install -e ".[core,dev]"
ruff check src/ tests/
mypy src/
STARTOUCH_CAN_INTERFACE=thirdhand-test pytest tests/ -q --ignore=tests/e2e/
pytest web-control/server/tests/ -q
```

测试接口名可避免离线资源锁测试与正在运行的 `can0` 控制服务冲突。

## 开源协议

MIT — 详见 [LICENSE](LICENSE)。
