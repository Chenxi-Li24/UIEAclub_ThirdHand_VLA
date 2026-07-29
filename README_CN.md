# ThirdHand VLA -- 桌面级机械臂 VLA 系统

> **UIEA 俱乐部** | Lumos Touch R1 + Lumos Ego + 云端VLA + 本地语音

基于 Python 的桌面机械臂控制系统，集成视觉感知（ArUco / YOLO）、云端 VLA 推理、
本地 ASR/TTS 语音交互和 Web 控制台。

## 架构

```
相机 -> 感知层(ArUco/YOLO) -> 状态机 -> 控制层(机械臂)
  |                              |
  +-- 云端VLA(推理建议) -----------+
  +-- 语音(ASR->NLU->意图) -------+
  +-- Web控制台(FastAPI+Three.js)-+
```

## 快速开始

```bash
git clone https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA
cd UIEAclub_ThirdHand_VLA
pip install -e ".[core]"
cp .env.example .env
python -m uiea_thirdhand_vla
# 浏览器打开 http://localhost:8000
```

### Startouch 真机网页控制

`web-control/` 是已完成真机联调的 Startouch SDK 直控页面，浏览器通过
WebSocket 连接 Ubuntu 服务，由 Ubuntu 直接控制 `can0` 上的机械臂。它独立于
上面的 VLA FastAPI 控制台，默认使用 `3000` 端口。

```bash
cp web-control/.env.example web-control/.env
web-control/scripts/setup_ubuntu.sh
web-control/scripts/start_ubuntu.sh
# 浏览器打开 http://<Ubuntu-IP>:3000
```

安装、CAN 总线、夹爪和安全说明见
[`web-control/README.md`](web-control/README.md)。

## 模块说明

| 模块 | 路径 | 功能 |
|------|------|------|
| perception | src/.../perception/ | 相机取流、标定、目标检测 |
| control | src/.../control/ | 机械臂控制、夹爪、安全监控 |
| interaction | src/.../interaction/ | 语音识别、合成、意图理解 |
| reasoning | src/.../reasoning/ | 云端 VLA API 客户端 |
| orchestration | src/.../orchestration/ | 状态机、任务编排 |
| web | src/.../web/ | FastAPI 后端 + 前端控制台 |
| logging | src/.../logging/ | 结构化数据记录 |
| config | src/.../config/ | YAML 配置管理 |
| web-control | web-control/ | 已联调的 Startouch SDK 真机控制页 |

## 配置

编辑 `configs/*.yaml` 适配你的硬件。详见 `docs/setup_guide.md`。

## 开源协议

MIT — 详见 [LICENSE](LICENSE)
# 固定 A/B 点 Pick and Place 一键演示

独立真机 worktree 当前配置为：垂直抬升 25 cm、移动速度 15%、低刚度自适应夹瓶，
并尝试连续执行 3 次 A→B→A 循环。请勿同时启动网页控制服务。

Ubuntu 本机启动：

```bash
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
bash scripts/demo_fixed_pick_place.sh
```

Windows PowerShell 远程启动：

```powershell
ssh -t robot-ubuntu "cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place && bash scripts/demo_fixed_pick_place.sh"
```

脚本会在运动前检查 worktree、分支、`can0`、点位、关节限位、速度、日志目录及
其他用户/控制进程。发生冲突时只输出 `RESOURCE_CONFLICT` 并退出，不干预对方。
正常和异常退出都会调用 cleanup；失败时会报告具体阶段和原因。
