from __future__ import annotations

import numpy as np
import pytest

from thirdhand_vision.core.camera import PinholeCamera, SeucmCamera
from thirdhand_vision.core.errors import ModelContractError
from thirdhand_vision.core.types import (
    CameraCalibrationRef,
    FrameBundle,
    FrameStamp,
    InstanceDetection,
)
from thirdhand_vision.geometry.pose import InstancePoseConfig
from thirdhand_vision.identity.memory import IdentityConfig, PersistentIdentityMemory
from thirdhand_vision.pipeline.config import VisionConfig
from thirdhand_vision.pipeline.offline import FusionCalibration, VisionPipeline


class BottleSegmenter:
    def predict(self, image_rgb):
        height, width = image_rgb.shape[:2]
        return (
            InstanceDetection(
                detection_id=0,
                label="bottle",
                score=0.95,
                bbox_xyxy=np.array([0.0, 0.0, width - 1.0, height - 1.0]),
                mask=np.ones((height, width), dtype=bool),
                image_shape=(height, width),
            ),
        )


class ConstantEncoder:
    model_id = "fixture-encoder"

    def encode(self, image_rgb, masks):
        return tuple(np.array([1.0, 0.0]) for _ in masks)


class BrokenEncoder:
    model_id = "broken"

    def encode(self, image_rgb, masks):
        return ()


def pipeline_config() -> VisionConfig:
    return VisionConfig(
        min_depth_m=0.1,
        max_depth_m=2.0,
        pose=InstancePoseConfig(5, 0, 3.5, 0.002),
        identity=IdentityConfig(
            0.4,
            0.03,
            0.8,
            0.2,
            0.2,
            500_000_000,
            300_000_000,
            1_500_000_000,
            1,
            0.8,
            0.5,
            8,
            12,
            64,
            2,
            0.025,
            200_000_000,
            1,
        ),
        extension_mode="strict",
    )


def build_pipeline(encoder=None, **kwargs) -> VisionPipeline:
    config = pipeline_config()
    return VisionPipeline(
        BottleSegmenter(),
        encoder or ConstantEncoder(),
        PersistentIdentityMemory(config.identity),
        config,
        **kwargs,
    )


def rgb_frame(frame_id: int = 1, calibration=None, depth=False) -> FrameBundle:
    stamp = FrameStamp("lumos_rgb", frame_id, frame_id * 100)
    return FrameBundle(
        rgb=np.zeros((9, 9, 3), dtype=np.uint8),
        depth_m=np.full((9, 9), 0.5, dtype=np.float32) if depth else None,
        depth_stamp=FrameStamp("d435_depth", frame_id, frame_id * 100) if depth else None,
        stamp=stamp,
        calibration=calibration,
    )


def calibration(validated: bool = True) -> FusionCalibration:
    return FusionCalibration(
        d435=PinholeCamera(100.0, 100.0, 4.0, 4.0, 9, 9),
        lumos=SeucmCamera(100.0, 100.0, 4.0, 4.0, 0.5, 1.0, 9, 9),
        t_lumos_from_d435=np.eye(4),
        t_output_from_lumos=np.eye(4),
        ref=CameraCalibrationRef(
            "sha256:fixture",
            validated,
            0.4 if validated else None,
        ),
    )


def test_pipeline_without_depth_returns_identity_but_no_pose() -> None:
    result = build_pipeline().process(rgb_frame())
    assert len(result.instances) == 1
    assert result.instances[0].identity_id is not None
    assert result.instances[0].pose is None
    assert "depth_unavailable" in result.blockers


def test_pipeline_with_depth_but_no_calibration_refuses_pose() -> None:
    result = build_pipeline().process(rgb_frame(depth=True))
    assert result.instances[0].pose is None
    assert "calibration_unavailable" in result.blockers


def test_pipeline_with_valid_calibration_returns_3d_pose() -> None:
    result = build_pipeline().process(rgb_frame(depth=True, calibration=calibration()))
    pose = result.instances[0].pose
    assert pose is not None
    assert pose.frame == "robot_base"
    assert pose.xyz_m[2] == pytest.approx(0.5)


def test_pipeline_rejects_descriptor_count_mismatch() -> None:
    with pytest.raises(ModelContractError, match="descriptor count"):
        build_pipeline(BrokenEncoder()).process(rgb_frame())

