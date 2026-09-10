"""Lazy DINO dense-feature adapter and dependency-free mask pooling."""

from __future__ import annotations

import inspect
from typing import Any, Iterable

import cv2
import numpy as np

from .contracts import ModelContractError, validated_rgb_image


def prepare_model_input(
    image_rgb: Any,
    masks: Iterable[Any],
    patch_size: int,
    max_long_side: int,
) -> tuple[np.ndarray, list[np.ndarray]]:
    image = validated_rgb_image(image_rgb)
    mask_list = [np.asarray(mask) for mask in masks]
    if not isinstance(patch_size, int) or patch_size < 1:
        raise ModelContractError("patch_size must be a positive integer")
    if not isinstance(max_long_side, int) or max_long_side < patch_size:
        raise ModelContractError("max_long_side must be an integer no smaller than patch_size")
    for mask in mask_list:
        if mask.shape != image.shape[:2] or mask.dtype != np.bool_:
            raise ModelContractError("every DINO mask must match the RGB image and be boolean")

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
        raise ModelContractError("native instance mask must be a 2D boolean array")
    if len(grid_shape) != 2:
        raise ModelContractError("patch grid shape must contain height and width")
    height, width = grid_shape
    if not isinstance(height, int) or not isinstance(width, int) or height < 1 or width < 1:
        raise ModelContractError("patch grid dimensions must be positive integers")
    coverage = cv2.resize(
        mask_array.astype(np.float32),
        (width, height),
        interpolation=cv2.INTER_AREA,
    )
    coverage = np.clip(np.asarray(coverage, dtype=float), 0.0, 1.0)
    coverage.setflags(write=False)
    return coverage


def pool_patch_descriptor(
    feature_map: Any,
    patch_coverage: Any,
    min_patch_coverage: float = 0.10,
) -> np.ndarray:
    features = np.asarray(feature_map, dtype=float)
    coverage = np.asarray(patch_coverage, dtype=float)
    threshold = float(min_patch_coverage)
    if features.ndim != 3 or features.shape[2] < 1:
        raise ModelContractError("feature map must have shape (Hp, Wp, D)")
    if not np.isfinite(features).all():
        raise ModelContractError("feature map must contain only finite values")
    if coverage.shape != features.shape[:2] or not np.isfinite(coverage).all():
        raise ModelContractError("patch coverage must match the feature grid and be finite")
    if np.any((coverage < 0.0) | (coverage > 1.0)):
        raise ModelContractError("patch coverage must be within [0, 1]")
    if not np.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ModelContractError("min_patch_coverage must be within [0, 1]")
    selected = coverage >= threshold
    if not selected.any():
        raise ModelContractError("instance mask covers no usable DINO patches")
    weights = coverage[selected]
    if float(weights.sum()) <= 0.0:
        raise ModelContractError("instance patch weights sum to zero")
    descriptor = np.average(features[selected], axis=0, weights=weights)
    norm = float(np.linalg.norm(descriptor))
    if not np.isfinite(norm) or norm <= 0.0:
        raise ModelContractError("pooled DINO descriptor has invalid norm")
    result = np.array(descriptor / norm, copy=True)
    result.setflags(write=False)
    return result


class DinoMaskEncoder:
    """Load one DINO backbone and pool one descriptor per native-image mask."""

    def __init__(
        self,
        model_id: str = "facebook/dinov2-small",
        device: str = "cuda:0",
        min_patch_coverage: float = 0.10,
        max_long_side: int = 640,
    ) -> None:
        if not model_id:
            raise ModelContractError("DINO model ID cannot be empty")
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModel
        except ImportError as error:
            raise ModelContractError(
                "DINO inference requires the isolated Torch/Transformers environment"
            ) from error
        self._torch = torch
        self.device = device
        self.model_id = model_id
        self.min_patch_coverage = float(min_patch_coverage)
        if not 0.0 <= self.min_patch_coverage <= 1.0:
            raise ModelContractError("min_patch_coverage must be within [0, 1]")
        self.processor = AutoImageProcessor.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(model_id)
        self.model.to(device).eval()
        patch_size = getattr(getattr(self.model, "config", None), "patch_size", None)
        if isinstance(patch_size, (tuple, list)):
            if len(patch_size) != 2 or patch_size[0] != patch_size[1]:
                raise ModelContractError("DINO adapter requires a square patch size")
            patch_size = patch_size[0]
        if not isinstance(patch_size, int) or patch_size < 1:
            raise ModelContractError("DINO model does not expose a valid patch size")
        self.patch_size = patch_size
        if not isinstance(max_long_side, int) or max_long_side < self.patch_size:
            raise ModelContractError("max_long_side must be no smaller than the DINO patch size")
        self.max_long_side = max_long_side

    def encode(self, image_rgb: Any, masks: Iterable[Any]) -> tuple[np.ndarray, ...]:
        image = validated_rgb_image(image_rgb)
        mask_list = [np.asarray(mask) for mask in masks]
        if not mask_list:
            return ()
        padded_image, padded_masks = prepare_model_input(
            image,
            mask_list,
            self.patch_size,
            self.max_long_side,
        )
        batch = self.processor(
            images=padded_image,
            return_tensors="pt",
            do_resize=False,
            do_center_crop=False,
        )
        inputs = {key: value.to(self.device) for key, value in batch.items()}
        forward_parameters = inspect.signature(self.model.forward).parameters
        if "interpolate_pos_encoding" in forward_parameters:
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
            raise ModelContractError("DINO token count is smaller than the inferred patch grid")
        patch_tokens = tokens[:, special_count:, :]
        if int(patch_tokens.shape[1]) != patch_count:
            raise ModelContractError("DINO token count does not match the inferred patch grid")
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
            for mask in padded_masks
        )
