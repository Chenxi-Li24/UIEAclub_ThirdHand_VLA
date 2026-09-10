"""Offline, hardware-free ThirdHand vision algorithms."""

from .core.errors import (
    ExtensionError,
    InputValidationError,
    ModelContractError,
    ModelLoadError,
    VisionSDKError,
)
from .core.types import (
    CameraCalibrationRef,
    FrameBundle,
    FrameStamp,
    InstanceDetection,
    PerceptionInstance,
    PerceptionResult,
    PoseEstimate,
)
from .pipeline import FusionCalibration, VisionConfig, VisionPipeline, load_vision_config

__version__ = "0.1.0"

__all__ = [
    "CameraCalibrationRef",
    "ExtensionError",
    "FrameBundle",
    "FrameStamp",
    "FusionCalibration",
    "InputValidationError",
    "InstanceDetection",
    "ModelContractError",
    "ModelLoadError",
    "PerceptionInstance",
    "PerceptionResult",
    "PoseEstimate",
    "VisionSDKError",
    "VisionConfig",
    "VisionPipeline",
    "__version__",
    "load_vision_config",
]
