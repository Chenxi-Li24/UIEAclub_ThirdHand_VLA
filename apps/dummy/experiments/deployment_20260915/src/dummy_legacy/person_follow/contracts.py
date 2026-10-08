from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Iterable


def _finite(values: Iterable[float], name: str) -> tuple[float, ...]:
    result = tuple(float(v) for v in values)
    if not result or not all(isfinite(v) for v in result):
        raise ValueError(f"{name} must contain finite numbers")
    return result


@dataclass(frozen=True)
class VisionObservation:
    schema_version: str
    frame_id: str
    captured_at: float
    camera_view_id: str
    calibration_hash: str
    model_id: str
    model_sha256: str
    identity_id: str | None
    identity_state: str
    center_px: tuple[float, float]
    bbox_xyxy: tuple[float, float, float, float]
    confidence: float
    latency_ms: float

    def __post_init__(self) -> None:
        center = _finite(self.center_px, "center_px")
        box = _finite(self.bbox_xyxy, "bbox_xyxy")
        if len(center) != 2 or len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("invalid observation geometry")
        if not isfinite(self.captured_at) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("invalid observation timing or confidence")
        object.__setattr__(self, "center_px", center)
        object.__setattr__(self, "bbox_xyxy", box)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MotionProposal:
    schema_version: str
    proposal_id: str
    session_id: str
    identity_id: str
    frame_id: str
    calibration_hash: str
    created_at: float
    expires_at: float
    joints_deg: tuple[float, ...]

    def __post_init__(self) -> None:
        joints = _finite(self.joints_deg, "joints_deg")
        if self.expires_at <= self.created_at:
            raise ValueError("proposal must expire after creation")
        object.__setattr__(self, "joints_deg", joints)

    def is_fresh(self, now: float) -> bool:
        return self.created_at <= now <= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["joints_deg"] = list(self.joints_deg)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MotionProposal":
        return cls(**value)
