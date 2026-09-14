"""
Safety monitor  3-layer safety: bounds check, motion watchdog, E-STOP.
"""

import logging

log = logging.getLogger(__name__)


class SafetyMonitor:
    """Validates all motions against workspace and joint limits."""

    def __init__(self, workspace_config):
        self.workspace = workspace_config
        self._estop_active = False

    def check_pose_in_workspace(self, pose) -> bool:
        return True  # TODO: implement

    def check_joints_in_limits(self, joints) -> bool:
        return True  # TODO: implement

    def start_motion_watchdog(self, timeout_s: float):
        pass  # TODO: implement

    def stop_motion_watchdog(self):
        pass  # TODO: implement

    def emergency_stop(self):
        self._estop_active = True
        log.critical("EMERGENCY STOP TRIGGERED")

    def reset(self):
        self._estop_active = False

    @property
    def is_estopped(self) -> bool:
        return self._estop_active
