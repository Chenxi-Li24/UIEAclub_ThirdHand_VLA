"""DINOv2 dense-feature adapter and dependency-light mask pooling."""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any

import cv2
import numpy as np

from thirdhand_vision.core.errors import ModelContractError, ModelLoadError
from thirdhand_vision.features.base import normalized_descriptor


def _validated_rgb(image_rgb: Any) -> np.ndarray:
    image = np.asarray(image_rgb)
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ModelContractError("DINO RGB input must be a uint8 HxWx3 array")
    return image


def prepare_model_input(
    image_rgb: Any,
    masks: Iterable[Any],
    patch_size: int,
    max_long_side: int,
) -> tuple[np.ndarray, list[np.ndarray]]:
    image = _validated_rgb(image_rgb)
    mask_list = [np.asarray(mask) for mask in masks]
    if not isinstance(patch_size, int) or patch_size < 1:
        raise ModelContractError("patch_size must be a positive integer")
    if not isinstance(max_long_side, int) or max_long_side < patch_size:
        raise ModelContractError("max_long_side must be at least patch_size")
    for mask in mask_list:
        if mask.shape != image.shape[:2] or mask.dtype != np.bool_:
            raise ModelContractError("DINO masks must be native-image boolean arrays")
    height, width = image.shape[:2]
    scale = min(1.0, max_long_side / max(height, width))
    resized_height = max(1, int(round(height * scale)))
    resized_width = max(1, int(round(width * scale)))
    if (resized_height, resized_width) == (height, width):
        resized_image = np.array(image, copy=True)
        resized_masks = [np.array(mask, copy=True) for mask in mask_list]
    else:
        resized_image = cv2.resize(
            image,
            (resized_width, resized_height),
            interpolation=cv2.INTER_AREA,
        )
        resized_masks = [
            cv2.resize(
                mask.astype(np.uint8),
                (resized_width, resized_height),
                interpolation=cv2.INTER_NEAREST,
            ).astype(bool)
            for mask in mask_list
        ]
    pad_height = (-resized_height) % patch_size
    pad_width = (-resized_width) % patch_size
    prepared_image = np.pad(
        resized_image,
        ((0, pad_height), (0, pad_width), (0, 0)),
        mode="edge",
    )
    prepared_masks = [
        np.pad(mask, ((0, pad_height), (0, pad_width)), constant_values=False)
        for mask in resized_masks
    ]
    return prepared_image, prepared_masks


def mask_to_patch_coverage(mask: Any, grid_shape: tuple[int, int]) -> np.ndarray:
    mask_array = np.asarray(mask)
    if mask_array.ndim != 2 or mask_array.dtype != np.bool_:
        raise ModelContractError("mask must be a boolean 2D array")
    if len(grid_shape) != 2 or any(not isinstance(value, int) or value < 1 for value in grid_shape):
        raise ModelContractError("grid_shape must contain positive dimensions")
    coverage = cv2.resize(
        mask_array.astype(np.float32),
        (grid_shape[1], grid_shape[0]),
        interpolation=cv2.INTER_AREA,
    )
    result = np.clip(np.asarray(coverage, dtype=float), 0.0, 1.0)
    result.setflags(write=False)
    return result


def pool_patch_descriptor(
    feature_map: Any,
    patch_coverage: Any,
    min_patch_coverage: float = 0.10,
) -> np.ndarray:
    features = np.asarray(feature_map, dtype=float)
    coverage = np.asarray(patch_coverage, dtype=float)
    threshold = float(min_patch_coverage)
    if features.ndim != 3 or features.shape[2] < 1 or not np.isfinite(features).all():
        raise ModelContractError("feature_map must be finite with shape (Hp, Wp, D)")
    if coverage.shape != features.shape[:2] or not np.isfinite(coverage).all():
        raise ModelContractError("patch coverage must match the feature grid")
    if np.any((coverage < 0.0) | (coverage > 1.0)):
        raise ModelContractError("patch coverage must be within [0, 1]")
    if not np.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ModelContractError("minimum patch coverage must be within [0, 1]")
    selected = coverage >= threshold
    if not selected.any():
        raise ModelContractError("instance mask covers no usable DINO patches")
    weights = coverage[selected]
    if float(weights.sum()) <= 0.0:
        raise ModelContractError("selected DINO patch weights sum to zero")
    pooled = np.average(features[selected], axis=0, weights=weights)
    return normalized_descriptor(pooled)


class DinoV2Encoder:
    """Load DINOv2 explicitly and pool one descriptor per instance mask."""

    def __init__(
        self,
        model_id: str = "facebook/dinov2-small",
        *,
        device: str = "cuda:0",
        min_patch_coverage: float = 0.10,
        max_long_side: int = 640,
        local_files_only: bool = True,
    ) -> None:
        if not isinstance(model_id, str) or not model_id:
            raise ModelLoadError("DINOv2 model ID must be a non-empty string")
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModel
        except ImportError as error:
            raise ModelLoadError("DINOv2 requires Torch and Transformers") from error
        self._torch = torch
        self.model_id = model_id
        self.device = device
        self.min_patch_coverage = float(min_patch_coverage)
        try:
            self.processor = AutoImageProcessor.from_pretrained(
                model_id,
                local_files_only=local_files_only,
            )
            self.model = AutoModel.from_pretrained(
                model_id,
                local_files_only=local_files_only,
            )
            self.model.to(device).eval()
        except Exception as error:
            raise ModelLoadError("DINOv2 model assets are unavailable locally") from error
        patch_size = getattr(getattr(self.model, "config", None), "patch_size", None)
        if isinstance(patch_size, (tuple, list)):
            if len(patch_size) != 2 or patch_size[0] != patch_size[1]:
                raise ModelContractError("DINOv2 requires a square patch size")
            patch_size = patch_size[0]
        if not isinstance(patch_size, int) or patch_size < 1:
            raise ModelContractError("DINOv2 model does not expose a valid patch size")
        self.patch_size = patch_size
        if not isinstance(max_long_side, int) or max_long_side < patch_size:
            raise ModelContractError("max_long_side must be at least the patch size")
        self.max_long_side = max_long_side

    def encode(self, image_rgb: Any, masks: Iterable[Any]) -> tuple[np.ndarray, ...]:
        image = _validated_rgb(image_rgb)
        mask_list = [np.asarray(mask) for mask in masks]
        if not mask_list:
            return ()
        prepared_image, prepared_masks = prepare_model_input(
            image,
            mask_list,
            self.patch_size,
            self.max_long_side,
        )
        batch = self.processor(
            images=prepared_image,
            return_tensors="pt",
            do_resize=False,
            do_center_crop=False,
        )
        inputs = {key: value.to(self.device) for key, value in batch.items()}
        if "interpolate_pos_encoding" in inspect.signature(self.model.forward).parameters:
            inputs["interpolate_pos_encoding"] = True
        with self._torch.inference_mode():
            outputs = self.model(**inputs)
        tokens = outputs.last_hidden_state
        pixel_values = inputs["pixel_values"]
        grid_shape = (
            int(pixel_values.shape[-2]) // self.patch_size,
            int(pixel_values.shape[-1]) // self.patch_size,
        )
        patch_count = grid_shape[0] * grid_shape[1]
        special_count = int(tokens.shape[1]) - patch_count
        if special_count < 0:
            raise ModelContractError("DINOv2 token count is smaller than the patch grid")
        patch_tokens = tokens[:, special_count:, :]
        if int(patch_tokens.shape[1]) != patch_count:
            raise ModelContractError("DINOv2 tokens do not match the patch grid")
        feature_map = (
            patch_tokens[0]
            .reshape(grid_shape[0], grid_shape[1], int(patch_tokens.shape[-1]))
            .detach()
            .cpu()
            .float()
            .numpy()
        )
        return tuple(
            pool_patch_descriptor(
                feature_map,
                mask_to_patch_coverage(mask, grid_shape),
                self.min_patch_coverage,
            )
            for mask in prepared_masks
        )
