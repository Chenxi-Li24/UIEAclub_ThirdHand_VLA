from dataclasses import replace

import numpy as np
import pytest

from thirdhand_va.common.contracts import RgbdFrame
from thirdhand_va.vision.geometry import (
    GeometryRejected,
    estimate_grasp_candidates,
    estimate_grasp_pose,
)

from test_grasp_pose import make_scene


def test_upright_bottle_generates_ranked_middle_body_candidates() -> None:
    candidates = estimate_grasp_candidates(*make_scene())

    assert len(candidates) >= 2
    assert candidates[0].quality >= candidates[-1].quality
    assert all(0.35 <= item.height_fraction <= 0.65 for item in candidates)
    assert candidates[0].clearance_m >= 0.01


def test_73mm_bottle_is_displayable_but_not_graspable() -> None:
    frame, candidate, config = make_scene()
    xyz = np.array(frame.xyz_camera_m, copy=True)
    yy, xx = np.indices(candidate.mask.shape)
    xyz[..., 0][candidate.mask] = 0.08 + (xx[candidate.mask] - 40.0) * 0.0041
    wide = RgbdFrame(
        frame.sequence,
        frame.monotonic_ns,
        frame.camera_serial,
        frame.rgb,
        xyz[..., 2],
        xyz,
    )

    with pytest.raises(GeometryRejected, match="grasp_width_exceeded"):
        estimate_grasp_pose(wide, candidate, config)


def test_partial_surface_bias_does_not_override_the_upright_table_prior() -> None:
    frame, candidate, config = make_scene()
    xyz = np.array(frame.xyz_camera_m, copy=True)
    points = xyz[candidate.mask]
    center = np.median(points, axis=0)
    angle = np.deg2rad(25.0)
    rotation = np.asarray([
        [np.cos(angle), -np.sin(angle), 0.0],
        [np.sin(angle), np.cos(angle), 0.0],
        [0.0, 0.0, 1.0],
    ])
    xyz[candidate.mask] = (points - center) @ rotation.T + center
    biased = replace(frame, xyz_camera_m=xyz, depth_m=xyz[..., 2])

    pose = estimate_grasp_pose(biased, candidate, config)

    assert abs(pose.axis[1]) > 0.98


def test_calibrated_base_vertical_is_an_explicit_axis_and_table_hint() -> None:
    frame, candidate, config = make_scene()

    candidates = estimate_grasp_candidates(
        frame,
        candidate,
        config,
        upright_direction_camera=np.asarray([0.0, -1.0, 0.0]),
    )

    assert abs(candidates[0].pose.axis[1]) > 0.999


def test_sideways_object_is_rejected_by_upright_height_width_geometry() -> None:
    frame, candidate, config = make_scene()
    xyz = np.array(frame.xyz_camera_m, copy=True)
    points = xyz[candidate.mask]
    center = np.median(points, axis=0)
    rotation = np.asarray([
        [0.0, -1.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    xyz[candidate.mask] = (points - center) @ rotation.T + center
    sideways = replace(frame, xyz_camera_m=xyz, depth_m=xyz[..., 2])

    with pytest.raises(GeometryRejected):
        estimate_grasp_pose(sideways, candidate, config)


def test_neighbor_inside_gripper_approach_corridor_is_rejected() -> None:
    frame, candidate, config = make_scene()
    xyz = np.array(frame.xyz_camera_m, copy=True)
    neighbor = np.zeros(candidate.mask.shape, dtype=bool)
    neighbor[10:52, 52:60] = True
    yy, _xx = np.indices(neighbor.shape)
    xyz[..., 0][neighbor] = 0.11
    xyz[..., 1][neighbor] = (yy[neighbor] - 31.0) * 0.002
    xyz[..., 2][neighbor] = 0.43
    crowded = replace(frame, xyz_camera_m=xyz, depth_m=xyz[..., 2])

    with pytest.raises(GeometryRejected, match="neighbor_approach_clearance"):
        estimate_grasp_candidates(
            crowded,
            candidate,
            config,
            scene_exclusion_mask=np.logical_or(candidate.mask, neighbor),
        )


def test_neighbor_corridor_uses_the_actual_base_x_insertion_axis() -> None:
    frame, candidate, config = make_scene()
    xyz = np.array(frame.xyz_camera_m, copy=True)
    neighbor = np.zeros(candidate.mask.shape, dtype=bool)
    neighbor[10:52, 52:60] = True
    yy, _xx = np.indices(neighbor.shape)
    xyz[..., 0][neighbor] = 0.03
    xyz[..., 1][neighbor] = (yy[neighbor] - 31.0) * 0.002
    xyz[..., 2][neighbor] = 0.45
    crowded = replace(frame, xyz_camera_m=xyz, depth_m=xyz[..., 2])
    exclusion = np.logical_or(candidate.mask, neighbor)

    assert estimate_grasp_candidates(
        crowded, candidate, config, scene_exclusion_mask=exclusion,
    )
    with pytest.raises(GeometryRejected, match="neighbor_approach_clearance"):
        estimate_grasp_candidates(
            crowded,
            candidate,
            config,
            scene_exclusion_mask=exclusion,
            approach_direction_camera=np.asarray([1.0, 0.0, 0.0]),
        )
