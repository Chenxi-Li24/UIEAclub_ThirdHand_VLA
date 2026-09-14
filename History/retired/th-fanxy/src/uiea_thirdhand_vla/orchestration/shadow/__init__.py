"""Read-only integrations for offline and shadow orchestration."""

from .grounding_dino import GroundingDinoCandidateProvider, OpenVocabCandidate
from .vision_events import VisionEvent, VisionEventAdapter
from .vision_sources import LatestVisionEventSource, VisionJsonlReplaySource

__all__ = [
    "GroundingDinoCandidateProvider",
    "LatestVisionEventSource",
    "OpenVocabCandidate",
    "VisionEvent",
    "VisionEventAdapter",
    "VisionJsonlReplaySource",
]
