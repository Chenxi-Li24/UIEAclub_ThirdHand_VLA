"""Authoritative six-axis velocity policy; no SDK import or hardware side effects."""
import json
import math
from pathlib import Path
import re

REFERENCE_DEG_S = (300, 300, 300, 1000, 1000, 1000)
MAX_SPEED_PERCENT = 0.05

def bounded_speed_percent(value=MAX_SPEED_PERCENT):
    speed = float(value)
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("speed percent must be finite and positive")
    return min(speed, MAX_SPEED_PERCENT)

def _validate_config_reference(config_path):
    text = config_path.read_text()
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
        raise ValueError(
            f"SDK joint speed reference must match 300/1000 deg/s before hardware connection: {config_path}"
        )


def validate_sdk_speed_reference(sdk_path, module_path=None):
    source_config = Path(sdk_path) / "src/config/robot_kinematics.yaml"
    _validate_config_reference(source_config)
    if module_path is None:
        return
    # stage_runtime packages the binding beside startouch_sdk/src/config.
    runtime_config = Path(module_path).resolve().parent / "src/config/robot_kinematics.yaml"
    _validate_config_reference(runtime_config)
    if runtime_config.read_bytes() != source_config.read_bytes():
        raise ValueError(
            "SDK runtime configuration differs from canonical source; "
            f"synchronize {runtime_config} from {source_config} before hardware connection"
        )
