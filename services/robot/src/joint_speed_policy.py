"""Authoritative six-axis velocity policy; no SDK import or hardware side effects."""
import json
import math
from pathlib import Path
import re

REFERENCE_DEG_S = (300, 300, 300, 1000, 1000, 1000)
MAX_SPEED_PERCENT = 0.10

def bounded_speed_percent(value=0.05):
    speed = float(value)
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("speed percent must be finite and positive")
    return min(speed, MAX_SPEED_PERCENT)

def validate_sdk_speed_reference(sdk_path):
    text = (Path(sdk_path) / "src/config/robot_kinematics.yaml").read_text()
    section = re.search(r"^joint_trajectory:\s*\n((?:[ \t].*\n|\n)*)", text, re.M)
    match = re.search(r"^  max_vel_limits:\s*(\[[^\n]+?\])", section.group(1), re.M) if section else None
    try:
        values = json.loads(match.group(1)) if match else None
        valid = isinstance(values, list) and len(values) == 6 and all(
            math.isfinite(float(value)) and abs(float(value) - math.radians(reference)) < 1e-9
            for value, reference in zip(values, REFERENCE_DEG_S))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError("SDK joint speed reference must match 300/1000 deg/s before hardware connection")
