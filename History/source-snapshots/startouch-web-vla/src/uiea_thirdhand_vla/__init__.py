"""
UIEA ThirdHand VLA — Desktop Robotic Arm Vision-Language-Action System.

A Python framework for controlling the Lumos Touch R1 desktop robotic arm
with vision-based perception (ArUco / YOLO), cloud VLA reasoning,
local ASR/TTS voice interaction, and a web-based control console.

Package structure:
    perception/   — Camera capture, calibration, object detection
    control/      — Robot arm, gripper, safety monitor
    interaction/  — ASR, TTS, NLU voice pipeline
    reasoning/    — Cloud VLA API client
    orchestration/— State machine, task definitions, central control
    web/          — FastAPI server + WebSocket + frontend
    logging/      — Structured per-run data recording
    config/       — YAML + Pydantic configuration management
    utils/        — Shared types, exceptions, helpers
"""

__version__ = "2.0.0"
__author__ = "UIEA Club"
