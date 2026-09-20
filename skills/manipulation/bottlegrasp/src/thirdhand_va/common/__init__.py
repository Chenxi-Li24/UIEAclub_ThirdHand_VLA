"""Shared configuration and data contracts for Vision and Action."""

from .config import VisionConfig
from .contracts import ArmState, RgbdFrame, VisionResult

__all__ = ["ArmState", "RgbdFrame", "VisionConfig", "VisionResult"]
