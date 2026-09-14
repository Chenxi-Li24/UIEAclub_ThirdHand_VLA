"""Independent same-instance gate between Lumos targets and D435 RGB masks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

from vision_models.contracts import InstanceDetection

from .camera_models import PinholeCamera
from .depth_registration import RegisteredDepth
from .geometry import transform_points, validate_transform
from .types import InvalidDataError


@dataclass(frozen=True)
class D435InstanceVerifierConfig:
    min_projected_points: int = 40
    min_support_fraction: float = 0.60
    ambiguity_margin: float = 0.10

    def __post_init__(self) -> None:
        if (
            isinstance(self.min_projected_points, bool)
            or not isinstance(self.min_projected_points, int)
            or self.min_projected_points < 1
        ):
            raise InvalidDataError("minimum projected points must be a positive integer")
        values = np.asarray(
            [self.min_support_fraction, self.ambiguity_margin], dtype=float
        )
        if not np.isfinite(values).all() or not 0.0 < values[0] <= 1.0:
            raise InvalidDataError("D435 verifier fractions are invalid")
        if not 0.0 <= values[1] < 1.0:
            raise InvalidDataError("D435 ambiguity margin is invalid")


@dataclass(frozen=True)
class D435InstanceVerification:
    lumos_detection_id: int
    d435_detection_id: int | None
    label: str
    verified: bool
    projected_points: int
    support_points: int
    support_fraction: float
    d435_bbox_xyxy: np.ndarray | None = field(compare=False)
    d435_mask: np.ndarray | None = field(compare=False, repr=False)
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("lumos_detection_id", "projected_points", "support_points"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidDataError(f"{name} must be a non-negative integer")
        if self.d435_detection_id is not None and (
            isinstance(self.d435_detection_id, bool)
            or not isinstance(self.d435_detection_id, int)
            or self.d435_detection_id < 0
        ):
            raise InvalidDataError("D435 detection ID must be non-negative")
        if not isinstance(self.label, str) or not self.label:
            raise InvalidDataError("D435 verification label is invalid")
        fraction = float(self.support_fraction)
        if not np.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
            raise InvalidDataError("D435 support fraction must be within [0, 1]")
        blockers = tuple(dict.fromkeys(self.blockers))
        if any(not isinstance(item, str) or not item for item in blockers):
            raise InvalidDataError("D435 verification blockers are invalid")
        if self.verified != (self.d435_detection_id is not None and not blockers):
            raise InvalidDataError("D435 verification state is inconsistent")
        if self.d435_bbox_xyxy is None:
            bbox = None
        else:
            bbox = np.array(self.d435_bbox_xyxy, dtype=float, copy=True)
            if bbox.shape != (4,) or not np.isfinite(bbox).all():
                raise InvalidDataError("D435 verification bounding box is invalid")
            bbox.setflags(write=False)
        if self.d435_mask is None:
            mask = None
        else:
            mask = np.array(self.d435_mask, dtype=bool, copy=True)
            if mask.ndim != 2 or not mask.any():
                raise InvalidDataError("D435 verification mask is invalid")
            mask.setflags(write=False)
        if self.verified and (bbox is None or mask is None):
            raise InvalidDataError("verified D435 instance requires its mask and box")
        object.__setattr__(self, "support_fraction", fraction)
        object.__setattr__(self, "d435_bbox_xyxy", bbox)
        object.__setattr__(self, "d435_mask", mask)
        object.__setattr__(self, "blockers", blockers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "d435_detection_id": self.d435_detection_id,
            "label": self.label,
            "projected_points": self.projected_points,
            "support_points": self.support_points,
            "support_fraction": self.support_fraction,
            "d435_bbox_xyxy": (
                None
                if self.d435_bbox_xyxy is None
                else self.d435_bbox_xyxy.tolist()
            ),
            "blockers": list(self.blockers),
        }


class D435InstanceVerifier:
    """Associate one Lumos target with an independently segmented D435 instance."""

    def __init__(self, config: D435InstanceVerifierConfig | None = None) -> None:
        self.config = config or D435InstanceVerifierConfig()
        if not isinstance(self.config, D435InstanceVerifierConfig):
            raise InvalidDataError("D435 instance verifier config is invalid")

    def evaluate(
        self,
        *,
        lumos_detection: InstanceDetection,
        d435_detections: Iterable[InstanceDetection],
        registered: RegisteredDepth,
        d435: PinholeCamera,
        t_d435_from_lumos: Any,
    ) -> D435InstanceVerification:
        if not isinstance(lumos_detection, InstanceDetection):
            raise InvalidDataError("Lumos detection is invalid")
        if not isinstance(registered, RegisteredDepth):
            raise InvalidDataError("registered depth is required")
        if not isinstance(d435, PinholeCamera):
            raise InvalidDataError("D435 camera model is required")
        if lumos_detection.mask.shape != registered.valid.shape:
            raise InvalidDataError("Lumos mask must match registered depth")
        detections = tuple(d435_detections)
        if any(not isinstance(item, InstanceDetection) for item in detections):
            raise InvalidDataError("D435 detections are invalid")
        for item in detections:
            if item.mask.shape != (d435.height, d435.width):
                raise InvalidDataError("instance mask must use native D435 pixels")

        points_lumos = registered.points_lumos_m[
            registered.valid & lumos_detection.mask
        ]
        if len(points_lumos):
            points_d435 = transform_points(
                validate_transform(t_d435_from_lumos), points_lumos
            )
            uv, projectable = d435.project(points_d435)
            uv = uv[projectable]
        else:
            uv = np.empty((0, 2), dtype=float)
        rounded = np.rint(uv).astype(np.int64) if len(uv) else np.empty((0, 2), int)
        in_frame = (
            (rounded[:, 0] >= 0)
            & (rounded[:, 0] < d435.width)
            & (rounded[:, 1] >= 0)
            & (rounded[:, 1] < d435.height)
        )
        rounded = rounded[in_frame]
        projected_points = len(rounded)

        candidates: list[tuple[float, int, InstanceDetection]] = []
        if projected_points >= self.config.min_projected_points:
            cols, rows = rounded[:, 0], rounded[:, 1]
            for detection in detections:
                if detection.label != lumos_detection.label:
                    continue
                support = int(np.count_nonzero(detection.mask[rows, cols]))
                fraction = support / projected_points
                if fraction >= self.config.min_support_fraction:
                    candidates.append((fraction, support, detection))
        candidates.sort(key=lambda item: (-item[0], -item[1], item[2].detection_id))
        if not candidates:
            return D435InstanceVerification(
                lumos_detection.detection_id,
                None,
                lumos_detection.label,
                False,
                projected_points,
                0,
                0.0,
                None,
                None,
                ("d435_instance_unverified",),
            )
        best_fraction, best_support, best = candidates[0]
        if (
            len(candidates) > 1
            and best_fraction - candidates[1][0] < self.config.ambiguity_margin
        ):
            return D435InstanceVerification(
                lumos_detection.detection_id,
                None,
                lumos_detection.label,
                False,
                projected_points,
                best_support,
                best_fraction,
                None,
                None,
                ("d435_instance_ambiguous",),
            )
        return D435InstanceVerification(
            lumos_detection.detection_id,
            best.detection_id,
            lumos_detection.label,
            True,
            projected_points,
            best_support,
            best_fraction,
            best.bbox_xyxy,
            best.mask,
            (),
        )


__all__ = [
    "D435InstanceVerification",
    "D435InstanceVerifier",
    "D435InstanceVerifierConfig",
]
