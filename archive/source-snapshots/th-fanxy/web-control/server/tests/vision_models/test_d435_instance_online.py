from __future__ import annotations

import numpy as np

from vision.calibration_gate import audit_handeye_calibration
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.d435_instance_verifier import (
    D435InstanceVerifier,
    D435InstanceVerifierConfig,
)
from vision.depth_registration import RegisteredDepth
from vision.dual_camera import DualCameraCalibrationBundle, DualCameraFusionContext
from vision.online_frames import RgbFrame
from vision.types import FrameStamp
from vision_models.contracts import InstanceDetection
from vision_models.d435_instance_online import OnlineD435InstanceAdapter


class FakeSegmenter:
    def __init__(self, detections):
        self.detections = tuple(detections)

    def predict(self, _image_rgb):
        return self.detections


def _detection(detection_id: int, mask: np.ndarray) -> InstanceDetection:
    rows, cols = np.nonzero(mask)
    return InstanceDetection(
        detection_id=detection_id,
        label="bottle",
        score=0.95,
        bbox_xyxy=np.array([cols.min(), rows.min(), cols.max() + 1, rows.max() + 1]),
        mask=mask,
    )


def _calibration() -> DualCameraCalibrationBundle:
    def audit(key: str):
        return audit_handeye_calibration(
            {
                key: np.eye(4).tolist(),
                "validation": {"reprojection_rmse_px": 0.3, "position_rmse_m": 0.004},
            },
            key,
        )

    return DualCameraCalibrationBundle.from_audits(
        d435=PinholeCamera(1.0, 1.0, 0.0, 0.0, 5, 5),
        lumos=SeucmCamera(1.0, 1.0, 0.0, 0.0, 0.5, 1.0, 5, 5),
        d435_to_lumos_audit=audit("T_lumos_from_d435"),
        lumos_to_flange_audit=audit("T_flange_from_lumos"),
    )


def test_online_adapter_runs_independent_d435_segmentation_and_association() -> None:
    mask = np.zeros((5, 5), dtype=bool)
    mask[1:4, 1:4] = True
    valid = mask.copy()
    points = np.full((5, 5, 3), np.nan)
    rows, cols = np.nonzero(valid)
    points[rows, cols] = np.column_stack((cols, rows, np.ones(len(rows))))
    z = np.full((5, 5), np.nan)
    z[valid] = 1.0
    registered = RegisteredDepth(
        z, np.where(valid, np.linalg.norm(points, axis=2), np.nan), valid,
        valid.astype(np.int32), points,
    )
    calibration = _calibration()
    context = DualCameraFusionContext(
        registered=registered,
        t_d435_from_lumos=np.eye(4),
        t_base_from_lumos=np.eye(4),
        source_stamp=FrameStamp("lumos_rgb+d435_depth", 9, 100),
        calibration_id=calibration.calibration.calibration_id,
        evidence_ids=(calibration.calibration.calibration_id,),
    )
    adapter = OnlineD435InstanceAdapter(
        FakeSegmenter((_detection(12, mask),)),
        D435InstanceVerifier(
            D435InstanceVerifierConfig(4, 0.7, 0.1)
        ),
    )

    results = adapter.evaluate(
        d435_rgb=RgbFrame(
            FrameStamp("d435_rgb", 9, 100),
            np.zeros((5, 5, 3), dtype=np.uint8),
        ),
        lumos_detections=(_detection(7, mask),),
        fusion_context=context,
        calibration=calibration,
    )

    assert len(results) == 1
    assert results[0].verified is True
    assert results[0].lumos_detection_id == 7
    assert results[0].d435_detection_id == 12
