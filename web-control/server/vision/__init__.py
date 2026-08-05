"""Offline-first vision geometry, tracking, and Dry Run safety core."""

from .camera_models import PinholeCamera, SeucmCamera
from .calibration_gate import CalibrationAudit, audit_handeye_calibration, sdk_pose_transform
from .depth_registration import RegisteredDepth, register_depth_to_lumos
from .dual_camera import (
    DualCameraCalibrationBundle,
    DualCameraConfig,
    DualCameraPerception,
    DualCameraResult,
    DualCameraTarget,
    StampedRobotPose,
    dual_camera_calibration_id,
)
from .online_frames import (
    CameraRoleMap,
    DepthFrame,
    FramePair,
    LatestFramePairer,
    RgbFrame,
)
from .dry_run import build_dry_run_report, generate_top_down_candidates
from .geometry import (
    invert_transform,
    make_transform,
    rpy_xyz_to_matrix,
    transform_points,
)
from .identity import (
    IdentityAssignment,
    IdentityObservation,
    IdentitySnapshot,
    IdentityStatus,
    IdentityUpdate,
    PersistentIdentityConfig,
    PersistentIdentityMemory,
)
from .instance_pose import InstancePoseConfig, estimate_instance_pose
from .object_memory import ObjectMemory, ObjectMemoryConfig
from .safety import SafetyConfig, evaluate_target_safety
from .tracking import MultiObjectTracker, TrackerConfig
from .types import (
    CalibrationRef,
    DryRunReport,
    FrameStamp,
    GraspCandidate,
    InvalidDataError,
    PoseEstimate,
    SafetyDecision,
    TrackObservation,
    TrackState,
)

__all__ = [
    "CalibrationRef",
    "CalibrationAudit",
    "DryRunReport",
    "DualCameraConfig",
    "DualCameraCalibrationBundle",
    "DualCameraPerception",
    "DualCameraResult",
    "DualCameraTarget",
    "StampedRobotPose",
    "FrameStamp",
    "GraspCandidate",
    "IdentityAssignment",
    "IdentityObservation",
    "IdentitySnapshot",
    "IdentityStatus",
    "IdentityUpdate",
    "InstancePoseConfig",
    "InvalidDataError",
    "MultiObjectTracker",
    "ObjectMemory",
    "ObjectMemoryConfig",
    "PinholeCamera",
    "PoseEstimate",
    "PersistentIdentityConfig",
    "PersistentIdentityMemory",
    "RegisteredDepth",
    "ReplayFormatError",
    "ReplayMetrics",
    "SafetyConfig",
    "SafetyDecision",
    "SeucmCamera",
    "TrackObservation",
    "TrackState",
    "TrackerConfig",
    "build_dry_run_report",
    "audit_handeye_calibration",
    "evaluate_target_safety",
    "dual_camera_calibration_id",
    "CameraRoleMap",
    "DepthFrame",
    "FramePair",
    "LatestFramePairer",
    "RgbFrame",
    "estimate_instance_pose",
    "generate_top_down_candidates",
    "invert_transform",
    "make_transform",
    "register_depth_to_lumos",
    "rpy_xyz_to_matrix",
    "sdk_pose_transform",
    "run_replay",
    "transform_points",
]


def __getattr__(name: str):
    """Load replay helpers lazily so `python -m vision.replay` stays warning-free."""

    if name in {"ReplayFormatError", "ReplayMetrics", "run_replay"}:
        from . import replay

        return getattr(replay, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
