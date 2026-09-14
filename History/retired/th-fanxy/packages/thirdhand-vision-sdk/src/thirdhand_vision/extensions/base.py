"""Narrow structural protocols for teammate-owned multimodal components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

import numpy as np

from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.core.types import FrameBundle, PerceptionResult


@dataclass(frozen=True)
class TargetSelection:
    identity_id: int
    score: float
    explanation: str

    def __post_init__(self) -> None:
        if isinstance(self.identity_id, bool) or not isinstance(self.identity_id, int) or self.identity_id < 0:
            raise InputValidationError("selection identity_id must be a non-negative integer")
        score = float(self.score)
        if not np.isfinite(score) or not 0.0 <= score <= 1.0:
            raise InputValidationError("selection score must be within [0, 1]")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise InputValidationError("selection explanation must be a non-empty string")
        object.__setattr__(self, "score", score)


@runtime_checkable
class ResultEnricher(Protocol):
    name: str

    def enrich(
        self,
        frame: FrameBundle,
        result: PerceptionResult,
        context: Mapping[str, Any],
    ) -> Mapping[int, Mapping[str, Any]]:
        """Return annotations keyed by existing detection ID."""
        raise NotImplementedError


@runtime_checkable
class TargetSelector(Protocol):
    name: str

    def select(
        self,
        result: PerceptionResult,
        context: Mapping[str, Any],
    ) -> Optional[TargetSelection]:
        """Select an identity already present in the perception result."""
        raise NotImplementedError

