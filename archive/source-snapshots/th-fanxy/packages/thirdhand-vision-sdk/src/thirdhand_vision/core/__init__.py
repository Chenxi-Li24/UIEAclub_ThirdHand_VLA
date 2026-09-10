"""Public contracts and dependency-light validation helpers."""

from .errors import (
    ExtensionError,
    InputValidationError,
    ModelContractError,
    ModelLoadError,
    VisionSDKError,
)
from .types import (
    CameraCalibrationRef,
    FrameBundle,
    FrameStamp,
    InstanceDetection,
    PerceptionInstance,
    PerceptionResult,
    PoseEstimate,
)

__all__ = [
    "CameraCalibrationRef",
    "ExtensionError",
    "FrameBundle",
    "FrameStamp",
    "InputValidationError",
    "InstanceDetection",
    "ModelContractError",
    "ModelLoadError",
    "PerceptionInstance",
    "PerceptionResult",
    "PoseEstimate",
    "VisionSDKError",
]

