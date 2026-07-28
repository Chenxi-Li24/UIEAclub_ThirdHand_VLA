# UIEA ThirdHand VLA -- System Architecture

## Overview
ThirdHand VLA is a desktop robotic arm system: vision perception + cloud VLA + local ASR/TTS + web console.

Hardware: Lumos Touch R1 (6-DOF) + Lumos Ego (RGB/ToF camera)
Platform: Ubuntu 20.04, Python 3.10+

## Architecture

```
main.py
  +-- FastAPI Server --> Web Console
  |   +-- /api/robot/*    REST: status, jog, home, estop
  |   +-- /api/camera/*   REST: stream, snapshot
  |   +-- /api/task/*     REST: start, stop, pause, status
  |   +-- /ws             WebSocket: real-time state + frames
  |
  +-- VoicePipeline (thread, optional)
  |   mic -> ASR(Whisper) -> NLU(local) -> Intent -> queue
  |
  +-- VLA Client (async, optional)
  |   frame + context -> cloud API -> suggestion -> FSM validates
  |
  +-- CentralControlUnit (facade)
      +-- Perception: camera + detector
      +-- Control: robot + gripper + safety
      +-- Logging: run_logger + image_recorder
```

## State Machine
IDLE -> DETECT -> APPROACH -> GRASP -> LIFT -> TRANSFER -> PLACE -> RETURN -> SUCCESS
(with ERROR and EMERGENCY_STOP from any state)

## Safety (3 layers)
1. Software bounds check before every motion
2. Motion watchdog timeout -> E-STOP
3. Keyboard (SPACE) or GPIO E-STOP

## Extensibility
- Detectors: BaseDetector ABC, swap ArUco/YOLO via config
- Tasks: BaseTask ABC, add new tasks in orchestration/tasks/
- Voice: swappable ASR/TTS/NLU backends
- VLA: Anthropic/DeepSeek/OpenAI-compatible

## Data Logging
logs/YYYY-MM-DD_HH-MM-SS_taskname/
  run_log.csv, state_transitions.jsonl, frames/, metadata.yaml
