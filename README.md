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
# Fixed A/B Pick and Place demo

The isolated real-arm workflow is configured for a 25 cm vertical lift,
15% motion speed, adaptive low-stiffness bottle grasping, and three requested
A-to-B-to-A cycles. Do not run the web controller at the same time.

Ubuntu local launch:

```bash
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
bash scripts/demo_fixed_pick_place.sh
```

Windows PowerShell remote launch:

```powershell
ssh -t robot-ubuntu "cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place && bash scripts/demo_fixed_pick_place.sh"
```

The launcher checks the worktree, branch, `can0`, point validity, joint
limits, speed, logs, and competing users/processes before motion. On a
conflict it prints `RESOURCE_CONFLICT` and does not interfere with the other
process. A failed run executes cleanup and reports the failed stage and cause.

Ubuntu desktop Start/Stop page:

```bash
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
bash scripts/open_fixed_pick_place_control.sh
```

The page opens at `http://127.0.0.1:8766/`. Its service does not connect to
`can0` while idle. “开始演示” launches the guarded script above; “停止并失能”
interrupts only the process launched by this page, runs cleanup, disables the
motors, and leaves the arm at its current pose. It never stops another user's
process. If the manual web controller or another robot task is active, the
page reports `RESOURCE_CONFLICT`.

While supervised step confirmation is required, the page enters
`WAITING_CONFIRMATION` before each logical action and enables the yellow
“执行下一步” button. The button confirms only the currently displayed stage.
After three consecutive validated real cycles, the configured unattended
demo can run without per-step confirmation.

Each safe logical route now sends one multi-waypoint SDK trajectory, so the
12° interpolation points no longer cause repeated stop/start motion. The arm
still stops at Home, the A/B raised points, and the grasp/release points where
a task action requires it.
