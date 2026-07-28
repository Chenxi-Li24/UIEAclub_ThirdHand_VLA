# ThirdHand VLA -- Desktop Robotic Arm Vision-Language-Action System

> **UIEA Club** | Lumos Touch R1 + Lumos Ego + Cloud VLA + Local ASR/TTS

A Python framework for controlling the Lumos Touch R1 desktop robotic arm
with vision-based perception (ArUco / YOLO), cloud VLA reasoning,
local ASR/TTS voice interaction, and a web-based control console.

## Architecture

```
Camera -> Perception (ArUco/YOLO) -> FSM -> Control (Robot Arm)
   |                                     |
   +-- Cloud VLA (reasoning) ------------+
   +-- Voice (ASR -> NLU -> Intent) -----+
   +-- Web Console (FastAPI + Three.js) -+
```

## Quick Start

```bash
git clone https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA
cd UIEAclub_ThirdHand_VLA
pip install -e ".[core]"
cp .env.example .env
python -m uiea_thirdhand_vla
# Open http://localhost:8000
```

### Startouch Hardware Web Control

`web-control/` contains the hardware-tested Startouch SDK control page. The
browser connects to an Ubuntu WebSocket service, which controls the robot
directly through `can0`. It is separate from the VLA FastAPI console above and
uses port `3000` by default.

```bash
cp web-control/.env.example web-control/.env
web-control/scripts/setup_ubuntu.sh
web-control/scripts/start_ubuntu.sh
# Open http://<Ubuntu-IP>:3000
```

See [`web-control/README.md`](web-control/README.md) for installation, CAN bus,
gripper, and safety details.

## Module Map

| Module | Path | Purpose |
|--------|------|---------|
| perception | src/.../perception/ | Camera, calibration, detection |
| control | src/.../control/ | Robot arm, gripper, safety |
| interaction | src/.../interaction/ | ASR, TTS, NLU |
| reasoning | src/.../reasoning/ | Cloud VLA API client |
| orchestration | src/.../orchestration/ | State machine, tasks |
| web | src/.../web/ | FastAPI + frontend |
| logging | src/.../logging/ | Per-run data recording |
| config | src/.../config/ | YAML + Pydantic |
| web-control | web-control/ | Hardware-tested Startouch SDK control page |

## Configuration

Edit `configs/*.yaml` for your hardware setup. See `docs/setup_guide.md`.

## License

MIT — see [LICENSE](LICENSE)
