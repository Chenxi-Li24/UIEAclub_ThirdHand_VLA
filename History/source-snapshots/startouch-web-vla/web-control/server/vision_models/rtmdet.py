"""Lazy MMDetection RTMDet instance-segmentation adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .contracts import InstanceDetection, ModelContractError, validated_rgb_image


def validate_model_labels(
    configured_labels: Sequence[str],
    dataset_meta: Any,
) -> tuple[str, ...]:
    labels = tuple(configured_labels)
    if not labels or not all(isinstance(label, str) and label for label in labels):
        raise ModelContractError("RTMDet labels must be non-empty strings")
    if not isinstance(dataset_meta, Mapping) or "classes" not in dataset_meta:
        raise ModelContractError("RTMDet checkpoint dataset metadata is missing classes")
    raw_model_labels = dataset_meta["classes"]
    if isinstance(raw_model_labels, (str, bytes)):
        raise ModelContractError("RTMDet dataset metadata must contain valid class names")
    try:
        model_labels = tuple(raw_model_labels)
    except TypeError as error:
        raise ModelContractError(
            "RTMDet dataset metadata must contain valid class names"
        ) from error
    if not model_labels or not all(
        isinstance(label, str) and label for label in model_labels
    ):
        raise ModelContractError("RTMDet dataset metadata must contain valid class names")
    if labels != model_labels:
        raise ModelContractError(
            f"configured RTMDet labels do not match checkpoint metadata: "
            f"{labels!r} != {model_labels!r}"
        )
    return labels


def _to_numpy(value: Any, name: str) -> np.ndarray:
    current = value
    for method in ("detach", "cpu"):
        callback = getattr(current, method, None)
        if callable(callback):
            current = callback()
    callback = getattr(current, "numpy", None)
    if callable(callback):
        current = callback()
    try:
        return np.asarray(current)
    except (TypeError, ValueError) as error:
        raise ModelContractError(f"cannot convert MMDetection {name} to NumPy") from error


def detections_from_mmdet(
    pred_instances: Any,
    labels: Sequence[str],
    image_shape: tuple[int, int],
    min_score: float,
) -> tuple[InstanceDetection, ...]:
    threshold = float(min_score)
    if not np.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ModelContractError("RTMDet score threshold must be within [0, 1]")
    if len(image_shape) != 2 or image_shape[0] < 1 or image_shape[1] < 1:
        raise ModelContractError("RTMDet image shape must contain positive height and width")
    if not labels or not all(isinstance(label, str) and label for label in labels):
        raise ModelContractError("RTMDet labels must be non-empty strings")
    if not hasattr(pred_instances, "masks"):
        raise ModelContractError("RTMDet result does not contain instance masks")
    try:
        boxes = _to_numpy(pred_instances.bboxes, "bboxes")
        scores = _to_numpy(pred_instances.scores, "scores")
        label_indices = _to_numpy(pred_instances.labels, "labels")
        masks = _to_numpy(pred_instances.masks, "masks")
    except AttributeError as error:
        raise ModelContractError("RTMDet result is missing required prediction fields") from error
    if boxes.ndim != 2 or boxes.shape[1] != 4:
        raise ModelContractError("RTMDet bboxes must have shape (N, 4)")
    count = len(boxes)
    if scores.shape != (count,) or label_indices.shape != (count,):
        raise ModelContractError("RTMDet prediction fields have inconsistent lengths")
    if masks.shape != (count, image_shape[0], image_shape[1]):
        raise ModelContractError("RTMDet masks must match the native image shape")

    detections = []
    for index in range(count):
        score = float(scores[index])
        if score < threshold:
            continue
        label_index = int(label_indices[index])
        if label_index < 0 or label_index >= len(labels):
            raise ModelContractError("RTMDet returned a label index outside the configured labels")
        mask = np.asarray(masks[index])
        if mask.dtype != np.bool_:
            mask = mask > 0.5
        detections.append(
            InstanceDetection(
                detection_id=index,
                label=labels[label_index],
                score=score,
                bbox_xyxy=boxes[index],
                mask=mask,
            )
        )
    detections.sort(key=lambda item: (-item.score, item.detection_id))
    return tuple(detections)


class RTMDetInstanceSegmenter:
    def __init__(
        self,
        config_path: Path | str,
        checkpoint_path: Path | str,
        labels: Sequence[str],
        device: str = "cuda:0",
        min_score: float = 0.35,
    ) -> None:
        self.config_path = Path(config_path).resolve()
        self.checkpoint_path = Path(checkpoint_path).resolve()
        if not self.config_path.is_file() or not self.checkpoint_path.is_file():
            raise ModelContractError("RTMDet config and checkpoint files must exist")
        if not labels or not all(isinstance(label, str) and label for label in labels):
            raise ModelContractError("RTMDet labels must be non-empty strings")
        self.labels = tuple(labels)
        self.device = device
        self.min_score = float(min_score)
        if not np.isfinite(self.min_score) or not 0.0 <= self.min_score <= 1.0:
            raise ModelContractError("RTMDet score threshold must be within [0, 1]")
        try:
            from mmdet.apis import inference_detector, init_detector
        except ImportError as error:
            raise ModelContractError(
                "RTMDet inference requires the isolated MMDetection environment"
            ) from error
        self._inference_detector = inference_detector
        self.model = init_detector(
            str(self.config_path),
            str(self.checkpoint_path),
            device=device,
        )
        self.labels = validate_model_labels(
            self.labels,
            getattr(self.model, "dataset_meta", None),
        )

    def predict(self, image_rgb: Any) -> tuple[InstanceDetection, ...]:
        image = validated_rgb_image(image_rgb)
        image_bgr = np.ascontiguousarray(image[..., ::-1])
        result = self._inference_detector(self.model, image_bgr)
        if isinstance(result, (list, tuple)):
            if len(result) != 1:
                raise ModelContractError("RTMDet returned an unexpected batch result")
            result = result[0]
        if not hasattr(result, "pred_instances"):
            raise ModelContractError("RTMDet result does not expose pred_instances")
        return detections_from_mmdet(
            result.pred_instances,
            self.labels,
            image.shape[:2],
            self.min_score,
        )
