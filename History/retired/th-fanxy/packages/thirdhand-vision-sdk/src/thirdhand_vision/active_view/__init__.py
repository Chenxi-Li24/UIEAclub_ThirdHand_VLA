"""Advisory observation-quality and viewpoint proposal algorithms."""

from .planner import evaluate_depth_quality, propose_refinement, select_observation_pose
from .types import (
    ActiveViewConfig,
    CoarseTargetEstimate,
    DepthQuality,
    ObservationPose,
    ObservationProposal,
)

__all__ = [
    "ActiveViewConfig",
    "CoarseTargetEstimate",
    "DepthQuality",
    "ObservationPose",
    "ObservationProposal",
    "evaluate_depth_quality",
    "propose_refinement",
    "select_observation_pose",
]

