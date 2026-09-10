from __future__ import annotations

import numpy as np
import pytest

from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.core.types import (
    FrameBundle,
    FrameStamp,
    InstanceDetection,
    PerceptionInstance,
    PerceptionResult,
    PoseEstimate,
)


def test_frame_bundle_rejects_non_uint8_rgb() -> None:
    with pytest.raises(InputValidationError, match="RGB image"):
        FrameBundle(
            rgb=np.zeros((8, 8, 3), dtype=np.float32),
            stamp=FrameStamp(source="fixture", frame_id=1, monotonic_ns=1),
        )


def test_frame_bundle_owns_read_only_copies() -> None:
    rgb = np.zeros((4, 5, 3), dtype=np.uint8)
    depth = np.ones((2, 3), dtype=np.float32)
    bundle = FrameBundle(
        rgb=rgb,
        depth_m=depth,
        stamp=FrameStamp(source="fixture", frame_id=7, monotonic_ns=11),
    )
    rgb[0, 0] = 255
    depth[0, 0] = 9.0
    assert bundle.rgb[0, 0].tolist() == [0, 0, 0]
    assert bundle.depth_m is not None
    assert bundle.depth_m[0, 0] == pytest.approx(1.0)
    assert not bundle.rgb.flags.writeable
    assert not bundle.depth_m.flags.writeable


def test_instance_detection_requires_native_image_mask() -> None:
    with pytest.raises(InputValidationError, match="mask"):
        InstanceDetection(
            detection_id=0,
            label="bottle",
            score=0.9,
            bbox_xyxy=np.array([0.0, 0.0, 3.0, 3.0]),
            mask=np.ones((3, 3), dtype=bool),
            image_shape=(4, 4),
        )


def test_pose_rejects_non_positive_semidefinite_covariance() -> None:
    covariance = np.diag([1.0, 1.0, -0.1])
    with pytest.raises(InputValidationError, match="positive semidefinite"):
        PoseEstimate(
            xyz_m=np.array([0.1, 0.2, 0.3]),
            covariance_m2=covariance,
            frame="robot_base",
            stamp=FrameStamp(source="fusion", frame_id=1, monotonic_ns=1),
            calibration_id="sha256:test",
        )


def test_perception_result_serializes_without_large_arrays() -> None:
    detection = InstanceDetection(
        detection_id=3,
        label="bottle",
        score=0.75,
        bbox_xyxy=np.array([1.0, 2.0, 5.0, 7.0]),
        mask=np.ones((8, 8), dtype=bool),
        image_shape=(8, 8),
    )
    instance = PerceptionInstance(
        detection=detection,
        identity_id=12,
        identity_status="confirmed",
        descriptor=np.ones(4) / 2.0,
        pose=None,
        reasons=("depth_unavailable",),
    )
    result = PerceptionResult(
        frame_id=1,
        monotonic_ns=2,
        instances=(instance,),
        blockers=("depth_unavailable",),
    )
    serialized = result.to_dict()
    assert serialized == {
        "frame_id": 1,
        "monotonic_ns": 2,
        "instances": [
            {
                "detection_id": 3,
                "label": "bottle",
                "score": 0.75,
                "bbox_xyxy": [1.0, 2.0, 5.0, 7.0],
                "identity_id": 12,
                "identity_status": "confirmed",
                "pose": None,
                "reasons": ["depth_unavailable"],
                "annotations": {},
            }
        ],
        "blockers": ["depth_unavailable"],
        "extension_errors": [],
        "selected_identity_id": None,
    }
    assert "mask" not in serialized["instances"][0]
    assert "descriptor" not in serialized["instances"][0]
