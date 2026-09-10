"""Online adapter for independent D435 RGB same-instance verification."""

from __future__ import annotations

from typing import Any

from vision.d435_instance_verifier import (
    D435InstanceVerification,
    D435InstanceVerifier,
)
from vision.dual_camera import DualCameraCalibrationBundle, DualCameraFusionContext
from vision.online_frames import RgbFrame

from .contracts import InstanceDetection, ModelContractError


class OnlineD435InstanceAdapter:
    """Segment D435 RGB and associate its instances with Lumos targets."""

    def __init__(self, segmenter: Any, verifier: D435InstanceVerifier) -> None:
        if not callable(getattr(segmenter, "predict", None)):
            raise ModelContractError("D435 adapter segmenter must expose predict(image_rgb)")
        if not isinstance(verifier, D435InstanceVerifier):
            raise ModelContractError("D435 adapter verifier is invalid")
        self.segmenter = segmenter
        self.verifier = verifier

    def evaluate(
        self,
        *,
        d435_rgb: RgbFrame,
        lumos_detections: Any,
        fusion_context: DualCameraFusionContext,
        calibration: DualCameraCalibrationBundle,
    ) -> tuple[D435InstanceVerification, ...]:
        if not isinstance(d435_rgb, RgbFrame):
            raise ModelContractError("D435 adapter requires a native RGB frame")
        if not isinstance(fusion_context, DualCameraFusionContext) or not isinstance(
            calibration, DualCameraCalibrationBundle
        ):
            raise ModelContractError("D435 adapter requires trusted fusion geometry")
        detections = tuple(lumos_detections)
        if any(not isinstance(item, InstanceDetection) for item in detections):
            raise ModelContractError("D435 adapter received invalid Lumos detections")
        d435_detections = tuple(self.segmenter.predict(d435_rgb.image_rgb))
        if any(not isinstance(item, InstanceDetection) for item in d435_detections):
            raise ModelContractError("D435 segmenter returned an invalid detection")
        try:
            return tuple(
                self.verifier.evaluate(
                    lumos_detection=detection,
                    d435_detections=d435_detections,
                    registered=fusion_context.registered,
                    d435=calibration.d435,
                    t_d435_from_lumos=fusion_context.t_d435_from_lumos,
                )
                for detection in detections
            )
        except Exception as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise ModelContractError(f"D435 same-instance verification failed: {error}") from error


__all__ = ["OnlineD435InstanceAdapter"]
