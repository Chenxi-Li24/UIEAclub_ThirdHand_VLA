"""
Gripper controller — TypeFZ / TypeLJ.
"""

import logging

log = logging.getLogger(__name__)


class Gripper:
    """Gripper control."""

    def __init__(self, config=None):
        self.config = config or {}
        self._position = 0.06  # current position in meters (open)

    def open(self, distance_m: float = 0.06):
        """Open gripper to position (meters)."""
        self._position = distance_m
        log.info(f"Gripper open → {distance_m:.3f}m")

    def close(self, distance_m: float = 0.02):
        """Close gripper to position (meters)."""
        self._position = distance_m
        log.info(f"Gripper close → {distance_m:.3f}m")

    def get_distance(self) -> float:
        """Get current opening distance (m)."""
        return self._position

    def is_grasped(self) -> bool:
        """Check if object is grasped."""
        return self._position < 0.03
