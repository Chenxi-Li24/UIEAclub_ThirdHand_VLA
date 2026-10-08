from __future__ import annotations

from dataclasses import dataclass

from ..visual_servo_gaze import VirtualGimbalCommand


@dataclass
class DumeFollowCommand:
    target_found: bool
    joints_deg: list[float]
    visual: VirtualGimbalCommand
    source: str = "mink"
    debug: dict | None = None
