"""One-frame-at-a-time hardware-free perception orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional

import numpy as np

from thirdhand_vision.core.camera import PinholeCamera, SeucmCamera
from thirdhand_vision.core.errors import (
    ExtensionError,
    InputValidationError,
    ModelContractError,
)
from thirdhand_vision.core.transforms import validate_transform
from thirdhand_vision.core.types import (
    CameraCalibrationRef,
    FrameBundle,
    FrameStamp,
    PerceptionInstance,
    PerceptionResult,
)
from thirdhand_vision.detection.base import InstanceSegmenter
from thirdhand_vision.extensions.base import ResultEnricher, TargetSelection, TargetSelector
from thirdhand_vision.features.base import FeatureEncoder, normalized_descriptor
from thirdhand_vision.geometry.depth import RegisteredDepth, register_depth
from thirdhand_vision.geometry.pose import estimate_instance_pose
from thirdhand_vision.identity.memory import (
    IdentityObservation,
    PersistentIdentityMemory,
)

from .config import VisionConfig


@dataclass(frozen=True)
class FusionCalibration:
    d435: PinholeCamera
    lumos: SeucmCamera
    t_lumos_from_d435: np.ndarray = field(compare=False, repr=False)
    t_output_from_lumos: np.ndarray = field(compare=False, repr=False)
    ref: CameraCalibrationRef

    def __post_init__(self) -> None:
        if not isinstance(self.d435, PinholeCamera) or not isinstance(self.lumos, SeucmCamera):
            raise InputValidationError("fusion calibration requires D435 and Lumos camera models")
        if not isinstance(self.ref, CameraCalibrationRef):
            raise InputValidationError("fusion calibration requires a calibration reference")
        object.__setattr__(
            self,
            "t_lumos_from_d435",
            validate_transform(self.t_lumos_from_d435),
        )
        object.__setattr__(
            self,
            "t_output_from_lumos",
            validate_transform(self.t_output_from_lumos),
        )


class VisionPipeline:
    """Compose injected algorithms without owning files, devices, threads or networks."""

    def __init__(
        self,
        segmenter: InstanceSegmenter,
        encoder: FeatureEncoder,
        identity_memory: PersistentIdentityMemory,
        config: VisionConfig,
        *,
        enrichers: Iterable[ResultEnricher] = (),
        selector: Optional[TargetSelector] = None,
    ) -> None:
        if not isinstance(segmenter, InstanceSegmenter):
            raise InputValidationError("segmenter must implement InstanceSegmenter")
        if not isinstance(encoder, FeatureEncoder):
            raise InputValidationError("encoder must implement FeatureEncoder")
        if not isinstance(identity_memory, PersistentIdentityMemory):
            raise InputValidationError("identity_memory must be PersistentIdentityMemory")
        if not isinstance(config, VisionConfig):
            raise InputValidationError("config must be VisionConfig")
        enricher_tuple = tuple(enrichers)
        if any(not isinstance(item, ResultEnricher) for item in enricher_tuple):
            raise InputValidationError("enrichers must implement ResultEnricher")
        if selector is not None and not isinstance(selector, TargetSelector):
            raise InputValidationError("selector must implement TargetSelector")
        self.segmenter = segmenter
        self.encoder = encoder
        self.identity_memory = identity_memory
        self.config = config
        self.enrichers = enricher_tuple
        self.selector = selector

    def _handle_extension_error(
        self,
        stage: str,
        plugin_name: str,
        error: BaseException,
        collected: list[str],
    ) -> None:
        if self.config.extension_mode == "strict":
            raise ExtensionError(stage, plugin_name, error) from error
        collected.append(f"{plugin_name}:{type(error).__name__}")

    def process(
        self,
        frame: FrameBundle,
        context: Optional[Mapping[str, Any]] = None,
    ) -> PerceptionResult:
        if not isinstance(frame, FrameBundle):
            raise InputValidationError("frame must be a FrameBundle")
        context_view = MappingProxyType(dict(context or {}))
        detections = tuple(self.segmenter.predict(frame.rgb))
        if any(item.image_shape != frame.rgb.shape[:2] for item in detections):
            raise ModelContractError("detector output does not match the frame shape")
        descriptors = tuple(
            normalized_descriptor(item)
            for item in self.encoder.encode(frame.rgb, (item.mask for item in detections))
        )
        if len(descriptors) != len(detections):
            raise ModelContractError("descriptor count must equal detection count")
        fusion_ns = max(
            frame.stamp.monotonic_ns,
            frame.stamp.monotonic_ns
            if frame.depth_stamp is None
            else frame.depth_stamp.monotonic_ns,
        )
        fusion_stamp = FrameStamp("fusion", frame.stamp.frame_id, fusion_ns)
        blockers: list[str] = []
        registered: Optional[RegisteredDepth] = None
        calibration = frame.calibration
        if frame.depth_m is None:
            blockers.append("depth_unavailable")
        elif calibration is None:
            blockers.append("calibration_unavailable")
        elif not isinstance(calibration, FusionCalibration):
            raise InputValidationError("frame calibration must be FusionCalibration")
        elif not calibration.ref.validated:
            blockers.append("calibration_not_validated")
        else:
            registered = register_depth(
                frame.depth_m,
                d435=calibration.d435,
                t_lumos_from_d435=calibration.t_lumos_from_d435,
                lumos=calibration.lumos,
                min_depth_m=self.config.min_depth_m,
                max_depth_m=self.config.max_depth_m,
            )
        if isinstance(calibration, FusionCalibration):
            self.identity_memory.set_calibration(calibration.ref)
        observations = []
        pose_by_detection = {}
        reasons_by_detection: dict[int, tuple[str, ...]] = {}
        for detection, descriptor in zip(detections, descriptors):
            pose = None
            reasons: list[str] = []
            if registered is not None and isinstance(calibration, FusionCalibration):
                try:
                    pose = estimate_instance_pose(
                        registered=registered,
                        mask=detection.mask,
                        t_output_from_lumos=calibration.t_output_from_lumos,
                        stamp=fusion_stamp,
                        calibration_id=calibration.ref.calibration_id,
                        config=self.config.pose,
                    )
                except InputValidationError:
                    reasons.append("insufficient_mask_depth")
            pose_by_detection[detection.detection_id] = pose
            reasons_by_detection[detection.detection_id] = tuple(reasons)
            observations.append(
                IdentityObservation(
                    observation_id=detection.detection_id,
                    label=detection.label,
                    confidence=detection.score,
                    visibility=1.0,
                    descriptor=descriptor,
                    stamp=fusion_stamp,
                    pose=pose,
                )
            )
        identity_update = self.identity_memory.update(observations, fusion_ns)
        instances = []
        for detection, descriptor, assignment in zip(
            detections,
            descriptors,
            identity_update.assignments,
        ):
            reasons = list(blockers)
            reasons.extend(reasons_by_detection[detection.detection_id])
            if assignment.reason:
                reasons.append(assignment.reason)
            instances.append(
                PerceptionInstance(
                    detection=detection,
                    identity_id=assignment.identity_id,
                    identity_status=assignment.status.value,
                    descriptor=descriptor,
                    pose=pose_by_detection[detection.detection_id],
                    reasons=tuple(dict.fromkeys(reasons)),
                )
            )
        result = PerceptionResult(
            frame_id=frame.stamp.frame_id,
            monotonic_ns=fusion_ns,
            instances=tuple(instances),
            blockers=tuple(blockers),
        )
        extension_errors: list[str] = []
        for enricher in self.enrichers:
            try:
                annotations = enricher.enrich(frame, result, context_view)
                if not isinstance(annotations, Mapping):
                    raise InputValidationError("enricher output must be a mapping")
                known = {item.detection.detection_id for item in result.instances}
                if any(key not in known or not isinstance(value, Mapping) for key, value in annotations.items()):
                    raise InputValidationError("enricher annotations must target existing detections")
                result = replace(
                    result,
                    instances=tuple(
                        replace(
                            item,
                            annotations={
                                **dict(item.annotations),
                                **dict(annotations.get(item.detection.detection_id, {})),
                            },
                        )
                        for item in result.instances
                    ),
                )
            except Exception as error:
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                self._handle_extension_error("enrich", enricher.name, error, extension_errors)
        selected_identity_id = None
        if self.selector is not None:
            try:
                selection = self.selector.select(result, context_view)
                if selection is not None:
                    if not isinstance(selection, TargetSelection):
                        raise InputValidationError("selector must return TargetSelection or None")
                    known_identities = {
                        item.identity_id for item in result.instances if item.identity_id is not None
                    }
                    if selection.identity_id not in known_identities:
                        raise InputValidationError("selector chose an identity absent from the result")
                    selected_identity_id = selection.identity_id
            except Exception as error:
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                self._handle_extension_error("select", self.selector.name, error, extension_errors)
        return replace(
            result,
            extension_errors=tuple(extension_errors),
            selected_identity_id=selected_identity_id,
        )

