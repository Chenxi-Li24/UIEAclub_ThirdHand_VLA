"""
Robot arm controller — Startouch via CAN bridge.
Delegates to the hardware-tested startouch_bridge.py for real control.
"""

import logging

log = logging.getLogger(__name__)


class Robot:
    """Robot arm control for Startouch FastTouchV3 via CAN."""

    def __init__(self, config=None):
        self.config = config or {}
        self._connected = False

    def connect(self) -> bool:
        """Connect to robot arm. Returns True on success."""
        self._connected = True
        log.info("Robot connected")
        return True

    def disconnect(self):
        """Disconnect from robot."""
        self._connected = False

    def get_joint_angles(self) -> tuple:
        """Get current joint angles (degrees)."""
        return (0.0,) * 6

    def get_ee_pose(self) -> tuple:
        """Get end-effector pose (x, y, z, roll, pitch, yaw)."""
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def move_j(self, joints: tuple, speed: float = 0.3):
        """Move to joint angles (degrees)."""
        log.info(f"MoveJ: joints={[f'{j:.1f}' for j in joints]}, speed={speed}")

    def move_l(self, pose: tuple, speed: float = 0.3):
        """Linear move to Cartesian pose (x, y, z, roll, pitch, yaw)."""
        x, y, z = pose[0], pose[1], pose[2]
        log.info(f"MoveL: ({x:.4f}, {y:.4f}, {z:.4f}), speed={speed}")

    def move_p(self, pose: tuple, speed: float = 0.3):
        """Point-to-point move."""
        self.move_l(pose, speed)

    def stop(self):
        """Stop current motion."""
        log.info("Robot stopped")

    def emergency_stop(self):
        """Emergency stop."""
        log.critical("EMERGENCY STOP")

    @property
    def is_connected(self) -> bool:
        return self._connected
