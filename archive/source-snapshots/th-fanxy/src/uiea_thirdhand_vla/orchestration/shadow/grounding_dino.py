"""Local-files-only Grounding DINO candidate proposals."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..runtime.trace import content_id

MAX_IMAGE_BYTES = 32 * 1024 * 1024


class GroundingDinoUnavailable(RuntimeError):
    """Raised when safe local Grounding DINO inference cannot be performed."""


class GroundingDinoConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    model_path: Path
    device: str = "cpu"
    box_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    text_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    max_candidates: int = Field(default=32, ge=1, le=1000)

    @field_validator("device")
    @classmethod
    def supported_device(cls, value: str) -> str:
        if value != "cpu" and re.fullmatch(r"cuda:\d+", value) is None:
            raise ValueError("device must be cpu or explicit cuda:<index>")
        return value

    @model_validator(mode="after")
    def checked_local_model(self) -> GroundingDinoConfig:
        if self.model_path.is_symlink():
            raise ValueError("model_path cannot be a symlink")
        if not self.model_path.is_dir():
            raise ValueError("model_path must be an existing local directory")
        return self


@dataclass(frozen=True)
class RawGroundingCandidate:
    label: str
    score: float
    box_xyxy_px: tuple[float, float, float, float]


class OpenVocabCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    candidate_id: str
    label: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    box_xyxy_px: tuple[float, float, float, float]
    evidence_id: str
    model_id: str = Field(min_length=1)
    actionable: Literal[False] = False


class GroundingDinoBackend(Protocol):
    def predict(
        self,
        image_path: Path,
        labels: tuple[str, ...],
        config: GroundingDinoConfig,
    ) -> tuple[RawGroundingCandidate, ...]: ...


def _default_dependency_loader() -> tuple[Any, Any, Any, Any]:
    import torch
    from PIL import Image
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    return torch, Image, AutoProcessor, AutoModelForZeroShotObjectDetection


class HuggingFaceGroundingDinoBackend:
    """Lazy Hugging Face backend that cannot fetch remote model files."""

    def __init__(
        self,
        *,
        dependency_loader: Callable[[], tuple[Any, Any, Any, Any]] | None = None,
    ) -> None:
        self._dependency_loader = dependency_loader or _default_dependency_loader
        self._loaded_path: Path | None = None
        self._torch: Any = None
        self._image_class: Any = None
        self._processor: Any = None
        self._model: Any = None

    def load(self, config: GroundingDinoConfig) -> None:
        if self._loaded_path == config.model_path:
            return
        try:
            torch, image_class, processor_class, model_class = self._dependency_loader()
            processor = processor_class.from_pretrained(
                str(config.model_path),
                local_files_only=True,
            )
            model = model_class.from_pretrained(
                str(config.model_path),
                local_files_only=True,
            )
            model = model.to(config.device)
            model.eval()
        except ImportError as exc:
            raise GroundingDinoUnavailable(
                f"Grounding DINO optional dependencies are unavailable: {exc}"
            ) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise GroundingDinoUnavailable(
                f"cannot load Grounding DINO from local model directory: {exc}"
            ) from exc
        self._loaded_path = config.model_path
        self._torch = torch
        self._image_class = image_class
        self._processor = processor
        self._model = model

    def predict(
        self,
        image_path: Path,
        labels: tuple[str, ...],
        config: GroundingDinoConfig,
    ) -> tuple[RawGroundingCandidate, ...]:
        self.load(config)
        try:
            with self._image_class.open(image_path) as opened:
                image = opened.convert("RGB")
                inputs = self._processor(
                    images=image,
                    text=[list(labels)],
                    return_tensors="pt",
                ).to(config.device)
                with self._torch.no_grad():
                    outputs = self._model(**inputs)
                results = self._processor.post_process_grounded_object_detection(
                    outputs,
                    threshold=config.box_threshold,
                    text_threshold=config.text_threshold,
                    target_sizes=[(image.height, image.width)],
                )
            result = results[0]
            text_labels = result.get("text_labels", result.get("labels", ()))
            return tuple(
                RawGroundingCandidate(
                    label=str(label),
                    score=float(score.item() if hasattr(score, "item") else score),
                    box_xyxy_px=tuple(
                        float(value)
                        for value in (box.tolist() if hasattr(box, "tolist") else box)
                    ),
                )
                for box, score, label in zip(
                    result["boxes"], result["scores"], text_labels, strict=True
                )
            )
        except GroundingDinoUnavailable:
            raise
        except (OSError, RuntimeError, TypeError, ValueError, KeyError, IndexError) as exc:
            raise GroundingDinoUnavailable(f"Grounding DINO inference failed: {exc}") from exc


def _normalized_label(value: str) -> str:
    normalized = " ".join(value.strip().lower().rstrip(".").split())
    for article in ("a ", "an ", "the "):
        if normalized.startswith(article):
            return normalized[len(article) :]
    return normalized


def _checked_image(path: Path) -> tuple[Path, str]:
    candidate = Path(path)
    if candidate.is_symlink():
        raise GroundingDinoUnavailable("Grounding DINO image cannot be a symlink")
    if not candidate.is_file():
        raise GroundingDinoUnavailable("Grounding DINO image must be a local regular file")
    try:
        data = candidate.read_bytes()
    except OSError as exc:
        raise GroundingDinoUnavailable(f"cannot read Grounding DINO image: {exc}") from exc
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise GroundingDinoUnavailable("Grounding DINO image size is outside (0, 32 MiB]")
    return candidate, "sha256:" + hashlib.sha256(data).hexdigest()


def _checked_raw(candidate: RawGroundingCandidate) -> tuple[str, float, tuple[float, ...]]:
    label = _normalized_label(candidate.label)
    score = float(candidate.score)
    box = tuple(float(value) for value in candidate.box_xyxy_px)
    if not label:
        raise GroundingDinoUnavailable("backend candidate label must be non-empty")
    if len(box) != 4 or not all(math.isfinite(value) for value in box):
        raise GroundingDinoUnavailable("backend candidate box must contain four finite values")
    x1, y1, x2, y2 = box
    if x1 < 0.0 or y1 < 0.0 or x2 <= x1 or y2 <= y1:
        raise GroundingDinoUnavailable("backend candidate box has invalid xyxy geometry")
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise GroundingDinoUnavailable("backend candidate score must be within [0, 1]")
    return label, score, box


class GroundingDinoCandidateProvider:
    """Turn open-vocabulary detections into non-actionable evidence proposals."""

    def __init__(
        self,
        config: GroundingDinoConfig,
        *,
        backend: GroundingDinoBackend | None = None,
    ) -> None:
        self.config = config
        self.backend = backend or HuggingFaceGroundingDinoBackend()

    def propose(
        self,
        image_path: Path,
        labels: tuple[str, ...],
    ) -> tuple[OpenVocabCandidate, ...]:
        image_path, evidence_id = _checked_image(image_path)
        normalized = tuple(_normalized_label(label) for label in labels)
        if not normalized or any(not label for label in normalized):
            raise GroundingDinoUnavailable("labels must be non-empty")
        if len(normalized) != len(set(normalized)):
            raise GroundingDinoUnavailable("labels must be unique after normalization")
        accepted: list[OpenVocabCandidate] = []
        for raw in self.backend.predict(image_path, normalized, self.config):
            label, score, box = _checked_raw(raw)
            if label not in normalized or score < self.config.box_threshold:
                continue
            body = {
                "box_xyxy_px": box,
                "evidence_id": evidence_id,
                "label": label,
                "model_id": self.config.model_path.name,
                "score": score,
            }
            accepted.append(
                OpenVocabCandidate(
                    candidate_id=content_id(body),
                    label=label,
                    score=score,
                    box_xyxy_px=box,
                    evidence_id=evidence_id,
                    model_id=self.config.model_path.name,
                )
            )
        accepted.sort(key=lambda item: (-item.score, item.label, item.box_xyxy_px))
        return tuple(accepted[: self.config.max_candidates])


__all__ = [
    "GroundingDinoBackend",
    "GroundingDinoCandidateProvider",
    "GroundingDinoConfig",
    "GroundingDinoUnavailable",
    "HuggingFaceGroundingDinoBackend",
    "OpenVocabCandidate",
    "RawGroundingCandidate",
]
