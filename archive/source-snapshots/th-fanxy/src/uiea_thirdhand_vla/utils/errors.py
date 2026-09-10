"""
Exception hierarchy for ThirdHand VLA.

Errors are caught at the state machine level; safety violations
trigger EMERGENCY_STOP.
"""


class ThirdHandError(Exception):
    """Base exception for all ThirdHand VLA errors."""


# --- Hardware Errors ---
class HardwareError(ThirdHandError):
    """Robot or camera hardware issues."""


class RobotNotConnected(HardwareError):
    """Robot arm is not reachable or not enabled."""


class RobotMotionFailed(HardwareError):
    """A motion command failed to execute."""


class CameraNotAvailable(HardwareError):
    """Camera device is not accessible."""


class GripperError(HardwareError):
    """Gripper operation failed."""


# --- Safety Violations ---
class SafetyViolation(ThirdHandError):
    """A safety constraint has been violated."""


class WorkspaceViolation(SafetyViolation):
    """Target pose is outside the defined workspace bounds."""


class JointLimitViolation(SafetyViolation):
    """Target joint angle exceeds hardware limits."""


class MotionTimeout(SafetyViolation):
    """Motion did not complete within the allowed time window."""


class EmergencyStop(SafetyViolation):
    """Emergency stop has been triggered (hardware or software)."""


# --- Detection Errors ---
class DetectionError(ThirdHandError):
    """Vision pipeline failure."""


class NoDetectionFound(DetectionError):
    """No objects/markers detected in the current frame."""


class CalibrationError(DetectionError):
    """Camera calibration data is missing or invalid."""


# --- Configuration Errors ---
class ConfigError(ThirdHandError):
    """Configuration loading or validation failure."""


# --- State Machine Errors ---
class IllegalTransition(ThirdHandError):
    """Attempted an invalid state machine transition."""


class TaskExecutionError(ThirdHandError):
    """A task step failed during execution."""
