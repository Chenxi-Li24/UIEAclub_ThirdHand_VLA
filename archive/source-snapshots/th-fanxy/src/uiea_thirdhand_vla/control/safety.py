"""
Safety monitor — workspace bounds, joint limits, emergency stop.
"""

import logging

log = logging.getLogger(__name__)


class Safety:
    """Validates all motions against workspace and joint limits."""

    # Startouch V3 joint limits (degrees)
    JOINT_LIMITS = [
        (-162, 162),    # J1
        (-12, 201),     # J2
        (-183, 0),      # J3
        (-98, 98),      # J4
        (-98, 98),      # J5
        (-164, 164),    # J6
    ]

    # Default workspace bounds (meters)
    WORKSPACE = {
        "x": (-0.3, 0.3),
        "y": (-0.3, 0.3),
        "z": (0.0, 0.35),
    }

    def __init__(self, config=None):
        cfg = config or {}
        self.workspace = cfg.get("workspace", self.WORKSPACE)
        self.joint_limits = cfg.get("joint_limits", self.JOINT_LIMITS)
        self._estop_active = False

    def check_pose_in_workspace(self, pose) -> bool:
        """Check if Cartesian pose is within workspace."""
        x, y, z = pose[0], pose[1], pose[2]
        wx = self.workspace["x"]
        wy = self.workspace["y"]
        wz = self.workspace["z"]

        if not (wx[0] <= x <= wx[1]):
            log.warning(f"X={x:.3f} outside workspace {wx}")
            return False
        if not (wy[0] <= y <= wy[1]):
            log.warning(f"Y={y:.3f} outside workspace {wy}")
            return False
        if not (wz[0] <= z <= wz[1]):
            log.warning(f"Z={z:.3f} outside workspace {wz}")
            return False
        return True

    def check_joints_in_limits(self, joints) -> bool:
        """Check if all joint angles are within limits."""
        for i, (angle, (lo, hi)) in enumerate(zip(joints, self.joint_limits)):
            if not (lo <= angle <= hi):
                log.warning(f"J{i+1}={angle:.1f}° outside [{lo}, {hi}]")
                return False
        return True

    def emergency_stop(self):
        """Trigger emergency stop."""
        self._estop_active = True
        log.critical("EMERGENCY STOP ACTIVE")

    def reset(self):
        """Reset emergency stop."""
        self._estop_active = False
        log.info("E-stop reset")

    @property
    def is_estopped(self) -> bool:
        return self._estop_active
