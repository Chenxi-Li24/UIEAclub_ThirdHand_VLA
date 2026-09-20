"""Lazy Grounding DINO + SAM2 adapter for full-resolution XVisio RGB frames."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.metadata
from pathlib import Path
import time
from typing import Any

import numpy as np
from numpy.typing import NDArray

from thirdhand_va.common.config import VisionConfig

from .interfaces import RawCandidate, canonical_prompt_label

PROMPTS = ("bottle",)
_POSITIVE = "bottle"


def cuda_inference_context(torch):
    """Run CUDA model kernels in safe FP16 autocast on modern NVIDIA GPUs."""
    return torch.autocast(device_type="cuda", dtype=torch.float16)


@dataclass(slots=True)
class _Models:
    torch: Any
    device: Any
    dino_processor: Any
    dino_model: Any
    sam_processor: Any
    sam_model: Any


class GroundedSamBackend:
    """Load cached learned models on first inference and reuse them thereafter."""

    def __init__(
        self,
        config: VisionConfig,
        *,
        local_files_only: bool = True,
    ) -> None:
        self.config = config
        self.local_files_only = local_files_only
        self._models: _Models | None = None
        self._inference_timings_ms = (0.0, 0.0)
        self._video_session: Any | None = None
        self._track_rows: dict[int, dict[str, Any]] = {}
        self._frame_count = 0

    def reset_tracking(self) -> None:
        """Forget video memory only when an explicit new selection starts."""
        self._discard_video_session()
        self._frame_count = 0

    def _discard_video_session(self) -> None:
        """Release SAM memory without changing the periodic frame counter."""
        if self._video_session is not None:
            reset = getattr(self._video_session, "reset_inference_session", None)
            if callable(reset):
                reset()
        self._video_session = None
        self._track_rows = {}

    @property
    def models_loaded(self) -> bool:
        return self._models is not None

    @property
    def model_cache_dir(self):
        if self.config.hf_home is None:
            return None
        return self.config.hf_home / "hub"

    @property
    def inference_timings_ms(self) -> tuple[float, float]:
        """Last complete Grounding DINO and SAM2 stage durations."""
        return self._inference_timings_ms

    def model_provenance(self) -> dict[str, str]:
        return {
            "vision_config_id": self.config.content_id,
            "camera_registration_id": self.config.camera_registration_id,
            "camera_mount_id": self.config.camera_mount_id,
            "grounding_model": self.config.grounding_model,
            "grounding_revision": self.config.grounding_revision,
            "grounding_weights_sha256": self.config.grounding_weights_sha256,
            "sam_model": self.config.sam_model,
            "sam_revision": self.config.sam_revision,
            "sam_weights_sha256": self.config.sam_weights_sha256,
            "transformers_version": importlib.metadata.version("transformers"),
        }

    def _load_models(self) -> _Models:
        if self._models is not None:
            return self._models
        import torch
        from transformers import (
            AutoModelForZeroShotObjectDetection,
            AutoProcessor,
            Sam2VideoModel,
            Sam2VideoProcessor,
        )

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for Grounding DINO and SAM2")
        device = torch.device("cuda")
        common: dict[str, Any] = {
            "local_files_only": self.local_files_only,
        }
        if self.model_cache_dir is not None:
            common["cache_dir"] = str(self.model_cache_dir)
        self._verify_pinned_weight(
            self.config.grounding_model,
            self.config.grounding_revision,
            self.config.grounding_weights_sha256,
        )
        self._verify_pinned_weight(
            self.config.sam_model,
            self.config.sam_revision,
            self.config.sam_weights_sha256,
        )
        dino_common = {**common, "revision": self.config.grounding_revision}
        sam_common = {**common, "revision": self.config.sam_revision}
        dino_processor = AutoProcessor.from_pretrained(
            self.config.grounding_model,
            **dino_common,
        )
        dino_model = AutoModelForZeroShotObjectDetection.from_pretrained(
            self.config.grounding_model,
            **dino_common,
        ).to(device).eval()
        sam_processor = Sam2VideoProcessor.from_pretrained(
            self.config.sam_model,
            **sam_common,
        )
        sam_model = Sam2VideoModel.from_pretrained(
            self.config.sam_model,
            **sam_common,
        ).to(device, dtype=torch.bfloat16).eval()
        self._models = _Models(
            torch=torch,
            device=device,
            dino_processor=dino_processor,
            dino_model=dino_model,
            sam_processor=sam_processor,
            sam_model=sam_model,
        )
        return self._models

    def _verify_pinned_weight(
        self, model_id: str, revision: str, expected_sha256: str
    ) -> None:
        if self.model_cache_dir is None:
            raise RuntimeError("pinned model verification requires hf_home")
        snapshot = (
            Path(self.model_cache_dir)
            / f"models--{model_id.replace('/', '--')}"
            / "snapshots"
            / revision
        )
        weight = next(
            (snapshot / name for name in ("model.safetensors", "pytorch_model.bin")
             if (snapshot / name).is_file()),
            None,
        )
        if weight is None:
            raise RuntimeError(f"pinned model weight missing: {model_id}@{revision}")
        with weight.open("rb") as stream:
            actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected_sha256:
            raise RuntimeError(f"pinned model weight hash mismatch: {model_id}@{revision}")

    def infer(self, rgb: NDArray[np.uint8]) -> tuple[RawCandidate, ...]:
        from PIL import Image

        image_array = np.asarray(rgb, dtype=np.uint8)
        if image_array.ndim != 3 or image_array.shape[2] != 3:
            raise ValueError("rgb must have shape (height, width, 3)")
        image = Image.fromarray(image_array, mode="RGB")
        models = self._load_models()
        self._frame_count += 1
        detect_due = self._video_session is None or (
            (self._frame_count - 1) % self.config.redetect_interval_frames == 0
        )
        if not detect_due:
            return self._track_frame(image, image_array, models)
        if self._video_session is not None:
            self._discard_video_session()
        return self._detect_and_seed(image, image_array, models)

    def _detect_and_seed(
        self,
        image,
        image_array: NDArray[np.uint8],
        models: _Models,
    ) -> tuple[RawCandidate, ...]:
        dino_started_ns = time.perf_counter_ns()
        inputs = models.dino_processor(
            images=image,
            text=[list(PROMPTS)],
            return_tensors="pt",
        ).to(models.device)
        with models.torch.inference_mode(), cuda_inference_context(models.torch):
            outputs = models.dino_model(**inputs)
        processed = models.dino_processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=self.config.grounding_box_threshold,
            text_threshold=self.config.grounding_text_threshold,
            target_sizes=[image.size[::-1]],
        )[0]
        dino_ms = (time.perf_counter_ns() - dino_started_ns) / 1_000_000
        labels = processed.get("text_labels", processed.get("labels", []))
        rows: list[dict[str, Any]] = []
        for index, (box, score, label) in enumerate(
            zip(processed["boxes"], processed["scores"], labels)
        ):
            rows.append(
                {
                    "detection_id": index,
                    "prompt_label": canonical_prompt_label(str(label)),
                    "score": float(score.item()),
                    "bbox_xyxy": tuple(float(value) for value in box.tolist()),
                    "mask": None,
                    "descriptor": None,
                }
            )
        positive_indices = [
            index
            for index, row in enumerate(rows)
            if row["prompt_label"] == _POSITIVE
        ]
        sam_ms = 0.0
        if positive_indices:
            sam_started_ns = time.perf_counter_ns()
            object_ids = [int(rows[index]["detection_id"]) for index in positive_indices]
            models_session = models.sam_processor.init_video_session(
                inference_device=models.device,
                # Keep long-lived mask memory on CPU.  The 8 GB GPU then holds
                # the models and only the latest vision features, preventing a
                # live session from growing until CUDA OOM.
                inference_state_device="cpu",
                processing_device=models.device,
                video_storage_device="cpu",
                max_vision_features_cache_size=1,
                dtype=models.torch.bfloat16,
            )
            sam_inputs = models.sam_processor(
                images=image,
                device=models.device,
                return_tensors="pt",
            )
            original_size = tuple(
                int(value) for value in sam_inputs.original_sizes[0]
            )
            # Transformers 4.56 builds box labels with a single-object shape;
            # registering prompts one object at a time avoids that upstream
            # batching defect while preserving one shared multi-object session.
            for row_index, object_id in zip(positive_indices, object_ids):
                models.sam_processor.add_inputs_to_inference_session(
                    inference_session=models_session,
                    frame_idx=0,
                    obj_ids=object_id,
                    input_boxes=sam_input_boxes((rows[row_index]["bbox_xyxy"],)),
                    original_size=original_size,
                )
            # Each single-object registration overwrites this upstream list;
            # restore all prompted IDs before the conditioning-frame forward.
            models_session.obj_with_new_inputs = list(object_ids)
            with models.torch.inference_mode(), cuda_inference_context(models.torch):
                sam_outputs = models.sam_model(
                    inference_session=models_session,
                    frame=sam_inputs.pixel_values[0],
                )
            masks = models.sam_processor.post_process_masks(
                [sam_outputs.pred_masks],
                original_sizes=sam_inputs.original_sizes,
            )[0]
            for row_index, mask_tensor in zip(positive_indices, masks):
                mask = np.asarray(
                    mask_tensor.squeeze().detach().to("cpu").numpy(), dtype=bool
                )
                rows[row_index]["mask"] = mask
                if mask.any():
                    rows[row_index]["descriptor"] = masked_rgb_descriptor(
                        image_array,
                        mask,
                        bins=self.config.reference_descriptor_bins,
                    )
                self._track_rows[int(rows[row_index]["detection_id"])] = {
                    "prompt_label": rows[row_index]["prompt_label"],
                    "score": rows[row_index]["score"],
                }
            self._video_session = models_session
            sam_ms = (time.perf_counter_ns() - sam_started_ns) / 1_000_000
        self._inference_timings_ms = (dino_ms, sam_ms)
        return tuple(RawCandidate(**row) for row in rows)

    def _track_frame(self, image, image_array: NDArray[np.uint8], models: _Models) -> tuple[RawCandidate, ...]:
        """Propagate stable object IDs through the next live frame."""
        sam_started_ns = time.perf_counter_ns()
        sam_inputs = models.sam_processor(
            images=image,
            device=models.device,
            return_tensors="pt",
        )
        with models.torch.inference_mode(), cuda_inference_context(models.torch):
            outputs = models.sam_model(
                inference_session=self._video_session,
                frame=sam_inputs.pixel_values[0],
            )
        masks = models.sam_processor.post_process_masks(
            [outputs.pred_masks],
            original_sizes=sam_inputs.original_sizes,
        )[0]
        rows: list[RawCandidate] = []
        for object_id, mask_tensor in zip(self._video_session.obj_ids, masks):
            mask = np.asarray(
                mask_tensor.squeeze().detach().to("cpu").numpy(), dtype=bool
            )
            if not mask.any():
                continue
            ys, xs = np.nonzero(mask)
            metadata = self._track_rows[int(object_id)]
            rows.append(RawCandidate(
                detection_id=int(object_id),
                prompt_label=str(metadata["prompt_label"]),
                score=float(metadata["score"]),
                bbox_xyxy=(
                    float(xs.min()), float(ys.min()),
                    float(xs.max() + 1), float(ys.max() + 1),
                ),
                mask=mask,
                descriptor=masked_rgb_descriptor(
                    image_array,
                    mask,
                    bins=self.config.reference_descriptor_bins,
                ),
            ))
        self._inference_timings_ms = (
            0.0,
            (time.perf_counter_ns() - sam_started_ns) / 1_000_000,
        )
        self._prune_video_history(int(outputs.frame_idx), keep_frames=32)
        return tuple(rows)

    def _prune_video_history(self, frame_idx: int, *, keep_frames: int) -> None:
        """Bound streaming memory while retaining SAM2's recent mask memory."""
        session = self._video_session
        if session is None or frame_idx <= keep_frames:
            return
        cutoff = frame_idx - keep_frames
        processed = getattr(session, "processed_frames", None)
        if isinstance(processed, dict):
            # HF 4.56 derives the next streaming index from dictionary length.
            # Keep keys/length monotonic, but release old frame tensors.
            for index in range(1, cutoff):
                if index in processed:
                    processed[index] = None
        elif isinstance(processed, list):
            for index in range(1, min(cutoff, len(processed))):
                processed[index] = None
        for obj_idx in range(session.get_obj_num()):
            outputs = session.output_dict_per_obj[obj_idx]["non_cond_frame_outputs"]
            for old_frame in tuple(outputs):
                if old_frame < cutoff:
                    outputs.pop(old_frame, None)
            tracked = session.frames_tracked_per_obj[obj_idx]
            for old_frame in tuple(tracked):
                if old_frame < cutoff:
                    tracked.pop(old_frame, None)


def masked_rgb_descriptor(
    rgb: NDArray[np.uint8],
    mask: NDArray[np.bool_],
    *,
    bins: int,
) -> NDArray[np.float32]:
    """Describe masked appearance and silhouette without using background pixels."""
    image = np.asarray(rgb, dtype=np.uint8)
    selected = np.asarray(mask, dtype=bool)
    if image.ndim != 3 or image.shape[2] != 3 or selected.shape != image.shape[:2]:
        raise ValueError("mask must share the RGB image grid")
    if bins < 2 or not selected.any():
        raise ValueError("descriptor requires a non-empty mask and at least two bins")
    pixels = image[selected]
    features: list[float] = []
    for channel in range(3):
        histogram, _ = np.histogram(
            pixels[:, channel],
            bins=bins,
            range=(0, 256),
        )
        features.extend((histogram / max(1, histogram.sum())).tolist())

    rows, columns = np.nonzero(selected)
    top, bottom = int(rows.min()), int(rows.max()) + 1
    left, right = int(columns.min()), int(columns.max()) + 1
    crop_mask = selected[top:bottom, left:right]
    row_profile = crop_mask.mean(axis=1)
    column_profile = crop_mask.mean(axis=0)
    features.extend(_resample_profile(row_profile, bins))
    features.extend(_resample_profile(column_profile, bins))

    crop_rgb = image[top:bottom, left:right].astype(np.float32) / 255.0
    for grid_y in range(4):
        y0 = crop_mask.shape[0] * grid_y // 4
        y1 = crop_mask.shape[0] * (grid_y + 1) // 4
        for grid_x in range(4):
            x0 = crop_mask.shape[1] * grid_x // 4
            x1 = crop_mask.shape[1] * (grid_x + 1) // 4
            cell_mask = crop_mask[y0:y1, x0:x1]
            if cell_mask.any():
                mean = crop_rgb[y0:y1, x0:x1][cell_mask].mean(axis=0)
            else:
                mean = np.zeros(3, dtype=np.float32)
            features.extend(float(value) for value in mean)
    descriptor = np.asarray(features, dtype=np.float32)
    norm = float(np.linalg.norm(descriptor))
    if norm <= 1e-12:
        raise ValueError("descriptor has zero norm")
    descriptor /= norm
    descriptor.setflags(write=False)
    return descriptor


def sam_input_boxes(
    boxes: tuple[tuple[float, float, float, float], ...],
) -> list[list[list[float]]]:
    """Convert immutable internal boxes to SAM2's strict three-list nesting."""
    return [[[float(value) for value in box] for box in boxes]]


def _resample_profile(profile: NDArray[np.floating], size: int) -> list[float]:
    if profile.size == 1:
        return [float(profile[0])] * size
    source = np.linspace(0.0, 1.0, profile.size)
    target = np.linspace(0.0, 1.0, size)
    return [float(value) for value in np.interp(target, source, profile)]
