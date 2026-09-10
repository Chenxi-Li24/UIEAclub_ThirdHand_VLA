from pathlib import Path

import numpy as np
import pytest

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate, RgbdFrame
from thirdhand_va.vision.geometry.grasp_pose import GeometryRejected, estimate_grasp_pose


def make_scene(
    *,
    holes: int = 0,
    outliers: int = 0,
    seed: int = 4,
) -> tuple[RgbdFrame, MaskCandidate, VisionConfig]:
    height, width = 60, 80
    mask = np.zeros((height, width), dtype=bool)
    mask[10:52, 31:50] = True
    yy, xx = np.indices((height, width))
    xyz = np.full((height, width, 3), np.nan, dtype=np.float32)
    xyz[..., 0] = (xx - 40.0) * 0.002
    xyz[..., 1] = 0.05
    xyz[..., 2] = 0.45 + (yy - 30.0) * 0.0002
    xyz[..., 0][mask] = 0.08 + (xx[mask] - 40.0) * 0.001
    xyz[..., 1][mask] = (yy[mask] - 31.0) * 0.002
    xyz[..., 2][mask] = 0.45
    rng = np.random.default_rng(seed)
    coordinates = np.argwhere(mask)
    if holes:
        selected = coordinates[rng.choice(len(coordinates), holes, replace=False)]
        xyz[selected[:, 0], selected[:, 1]] = np.nan
    if outliers:
        selected = coordinates[rng.choice(len(coordinates), outliers, replace=False)]
        xyz[selected[:, 0], selected[:, 1], 2] = 0.95
    depth = xyz[..., 2].copy()
    frame = RgbdFrame(
        sequence=1,
        monotonic_ns=10,
        camera_serial="250801DR48FP25002738",
        rgb=np.zeros((height, width, 3), dtype=np.uint8),
        depth_m=depth,
        xyz_camera_m=xyz,
    )
    candidate = MaskCandidate(
        detection_id=1,
        label="coca-cola plastic bottle",
        score=0.9,
        bbox_xyxy=(0.0, 0.0, 20.0, 20.0),
        mask=mask,
        authorized=True,
        reasons=(),
    )
    return frame, candidate, VisionConfig.from_yaml(Path("configs/vision.yaml"))


def test_pose_uses_mask_xyz_not_bbox_center() -> None:
    pose = estimate_grasp_pose(*make_scene())

    np.testing.assert_allclose(pose.point_m, (0.08, 0.0, 0.45), atol=0.005)
    assert abs(pose.axis[1]) > 0.98
    assert np.linalg.norm(pose.axis) == pytest.approx(1.0)
    assert np.linalg.norm(pose.approach) == pytest.approx(1.0)
    assert 0.015 < pose.width_m < 0.025
    assert pose.height_m is not None and pose.height_m > 0.05


def test_pose_survives_holes_and_outliers() -> None:
    pose = estimate_grasp_pose(*make_scene(holes=100, outliers=80))

    assert pose.valid_points >= 400
    assert max(pose.position_std_m) < 0.01
    np.testing.assert_allclose(pose.point_m, (0.08, 0.0, 0.45), atol=0.006)


def test_insufficient_depth_is_rejected() -> None:
    frame, candidate, config = make_scene()
    xyz = np.full_like(frame.xyz_camera_m, np.nan)
    valid = np.argwhere(candidate.mask)[:10]
    xyz[valid[:, 0], valid[:, 1]] = frame.xyz_camera_m[valid[:, 0], valid[:, 1]]
    sparse = RgbdFrame(
        sequence=frame.sequence,
        monotonic_ns=frame.monotonic_ns,
        camera_serial=frame.camera_serial,
        rgb=frame.rgb,
        depth_m=xyz[..., 2],
        xyz_camera_m=xyz,
    )

    with pytest.raises(GeometryRejected, match="depth_insufficient"):
        estimate_grasp_pose(sparse, candidate, config)


def test_depth_surface_spread_does_not_inflate_gripper_width() -> None:
    frame, candidate, config = make_scene()
    xyz = np.array(frame.xyz_camera_m, copy=True)
    yy, _xx = np.indices(candidate.mask.shape)
    xyz[..., 2][candidate.mask] += (yy[candidate.mask] % 7) * 0.01
    varied = RgbdFrame(
        frame.sequence, frame.monotonic_ns, frame.camera_serial,
        frame.rgb, xyz[..., 2], xyz,
    )

    pose = estimate_grasp_pose(varied, candidate, config)

    assert pose.width_m <= config.max_grasp_width_m
    assert 0.015 < pose.width_m < 0.025
