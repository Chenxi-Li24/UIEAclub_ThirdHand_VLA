"""Lazy MMDetection RTMDet instance-segmentation adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from thirdhand_vision.core.errors import ModelContractError, ModelLoadError
from thirdhand_vision.core.types import InstanceDetection


def _validated_rgb(image_rgb: Any) -> np.ndarray:
    image = np.asarray(image_rgb)
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ModelContractError("model RGB input must be a uint8 HxWx3 array")
    return image


def validate_model_labels(
    configured_labels: Sequence[str],
    dataset_meta: Any,
) -> tuple[str, ...]:
    labels = tuple(configured_labels)
    if not labels or not all(isinstance(label, str) and label for label in labels):
        raise ModelContractError("RTMDet labels must be non-empty strings")
    if not isinstance(dataset_meta, Mapping) or "classes" not in dataset_meta:
        raise ModelContractError("RTMDet checkpoint metadata is missing classes")
    raw_classes = dataset_meta["classes"]
    if isinstance(raw_classes, (str, bytes)):
        raise ModelContractError("RTMDet checkpoint classes must be a sequence")
    try:
        checkpoint_labels = tuple(raw_classes)
    except TypeError as error:
        raise ModelContractError("RTMDet checkpoint classes must be a sequence") from error
    if labels != checkpoint_labels:
        raise ModelContractError(
            f"configured RTMDet labels do not match checkpoint metadata: "
            f"{labels!r} != {checkpoint_labels!r}"
        )
    return labels


def _to_numpy(value: Any, name: str) -> np.ndarray:
    current = value
    for method_name in ("detach", "cpu"):
        method = getattr(current, method_name, None)
        if callable(method):
            current = method()
    numpy_method = getattr(current, "numpy", None)
    if callable(numpy_method):
        current = numpy_method()
    try:
        return np.asarray(current)
    except (TypeError, ValueError) as error:
        raise ModelContractError(f"cannot convert RTMDet {name} to NumPy") from error


def detections_from_mmdet(
    pred_instances: Any,
    labels: Sequence[str],
    image_shape: tuple[int, int],
    min_score: float,
) -> tuple[InstanceDetection, ...]:
    threshold = float(min_score)
    if not np.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ModelContractError("RTMDet score threshold must be within [0, 1]")
    if not hasattr(pred_instances, "masks"):
        raise ModelContractError("RTMDet result does not contain instance masks")
    try:
        boxes = _to_numpy(pred_instances.bboxes, "bboxes")
        scores = _to_numpy(pred_instances.scores, "scores")
        label_indices = _to_numpy(pred_instances.labels, "labels")
        masks = _to_numpy(pred_instances.masks, "masks")
    except AttributeError as error:
        raise ModelContractError("RTMDet result is missing prediction fields") from error
    if boxes.ndim != 2 or boxes.shape[1] != 4:
        raise ModelContractError("RTMDet boxes must have shape (N, 4)")
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
            raise ModelContractError("RTMDet label index is outside configured labels")
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
                image_shape=image_shape,
            )
        )
    detections.sort(key=lambda item: (-item.score, item.detection_id))
    return tuple(detections)


class RTMDetSegmenter:
    """Load RTMDet only when a caller explicitly constructs this adapter."""

    def __init__(
        self,
        config_path: Path | str,
        checkpoint_path: Path | str,
        labels: Sequence[str],
        *,
        device: str = "cuda:0",
        min_score: float = 0.35,
    ) -> None:
        self.config_path = Path(config_path).expanduser().resolve()
        self.checkpoint_path = Path(checkpoint_path).expanduser().resolve()
        if not self.config_path.is_file() or not self.checkpoint_path.is_file():
            raise ModelLoadError("RTMDet config and checkpoint must be explicit local files")
        self.labels = tuple(labels)
        self.device = device
        self.min_score = float(min_score)
        try:
            from mmdet.apis import inference_detector, init_detector
        except ImportError as error:
            raise ModelLoadError("RTMDet requires a compatible MMDetection environment") from error
        try:
            self.model = init_detector(
                str(self.config_path),
                str(self.checkpoint_path),
                device=device,
            )
        except Exception as error:
            raise ModelLoadError("RTMDet model initialization failed") from error
        self._inference_detector = inference_detector
        self.labels = validate_model_labels(
            self.labels,
            getattr(self.model, "dataset_meta", None),
        )

    def predict(self, image_rgb: Any) -> tuple[InstanceDetection, ...]:
        image = _validated_rgb(image_rgb)
        image_bgr = np.ascontiguousarray(image[..., ::-1])
        result = self._inference_detector(self.model, image_bgr)
        if isinstance(result, (list, tuple)):
            if len(result) != 1:
                raise ModelContractError("RTMDet returned an unexpected batch")
            result = result[0]
        if not hasattr(result, "pred_instances"):
            raise ModelContractError("RTMDet result is missing pred_instances")
        return detections_from_mmdet(
            result.pred_instances,
            self.labels,
            image.shape[:2],
            self.min_score,
        )

