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

## Configuration

Edit `configs/*.yaml` for your hardware setup. See `docs/setup_guide.md`.

## License

MIT — see [LICENSE](LICENSE)
