import numpy as np
import json
import subprocess
import sys
import cv2
from pathlib import Path

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate, RgbdFrame
from thirdhand_va.vision.observer import (
    build_candidate_observations,
    find_locked_observation,
    apply_rotated_mask_aspect_gate,
    attach_supervised_base_candidate,
    capture_wall_time_ms,
    finalize_observation_freshness,
    require_flange_pose,
    robust_transverse_width_m,
    select_base_height_band,
    estimate_base_center_from_surface,
    wait_for_pose_covering_frame,
)


def _scene(*, captured_ns: int = 1_000_000_000):
    config = VisionConfig.from_yaml("configs/vision.yaml")
    rgb = np.zeros((480, 640, 3), dtype=np.uint8)
    xyz = np.full((480, 640, 3), np.nan, dtype=np.float32)
    candidates = []
    for detection_id, x0, depth in ((7, 80, 0.35), (3, 300, 0.42)):
        mask = np.zeros((480, 640), dtype=bool)
        mask[100:220, x0 : x0 + 30] = True
        yy, xx = np.nonzero(mask)
        xyz[yy, xx, 0] = (xx - 320) * 0.001
        xyz[yy, xx, 1] = (yy - 240) * 0.001
        xyz[yy, xx, 2] = depth
        candidates.append(MaskCandidate(
            detection_id=detection_id,
            label="bottle",
            score=0.9,
            bbox_xyxy=(x0, 100, x0 + 30, 220),
            mask=mask,
            authorized=True,
        ))
    frame = RgbdFrame(
        sequence=12,
        monotonic_ns=captured_ns,
        camera_serial=config.camera_serial,
        rgb=rgb,
        depth_m=xyz[..., 2],
        xyz_camera_m=xyz,
    )
    return config, frame, tuple(reversed(candidates))


def _pose(*, ts=995, stationary=True, stationary_since_ms=900):
    return {
        "pose_frame": "sdk_tool",
        "tcp_position_m": [0.4, 0.0, 0.2],
        "tcp_euler_rad": [0.0, 0.8, 0.49],
        "ts": ts,
        "stationary": stationary,
        "stationary_since_ms": stationary_since_ms,
    }


def test_waits_for_next_real_stationary_pose_that_covers_capture() -> None:
    samples = iter((_pose(ts=995), _pose(ts=1005)))
    clock = {"ns": 100_000_000}
    reads = []

    def read_pose():
        value = next(samples)
        reads.append(value)
        return value

    def sleep(seconds):
        clock["ns"] += int(seconds * 1_000_000_000)

    result = wait_for_pose_covering_frame(
        read_pose,
        capture_wall_ms=1000,
        captured_monotonic_ns=0,
        monotonic_ns=lambda: clock["ns"],
        sleep=sleep,
    )

    assert result is reads[1]
    assert result["ts"] == 1005
    assert clock["ns"] == 105_000_000


def test_motion_and_old_inflight_frame_never_wait_for_revalidation() -> None:
    for pose in (
        _pose(ts=995, stationary=False),
        _pose(ts=995, stationary_since_ms=1001),
    ):
        reads = 0
        slept = []

        def read_pose():
            nonlocal reads
            reads += 1
            return pose

        result = wait_for_pose_covering_frame(
            read_pose,
            capture_wall_ms=1000,
            captured_monotonic_ns=0,
            monotonic_ns=lambda: 100_000_000,
            sleep=slept.append,
        )

        assert result is pose
        assert reads == 1
        assert slept == []


def test_pose_wait_stops_at_frame_age_budget_without_fabricating_timestamp() -> None:
    pose = _pose(ts=995)
    clock = {"ns": 200_000_000}

    def sleep(seconds):
        clock["ns"] += int(seconds * 1_000_000_000)

    result = wait_for_pose_covering_frame(
        lambda: pose,
        capture_wall_ms=1000,
        captured_monotonic_ns=0,
        monotonic_ns=lambda: clock["ns"],
        sleep=sleep,
    )

    assert result is pose
    assert result["ts"] == 995
    assert clock["ns"] == 250_000_000


def test_measured_bottle_diameter_stabilizes_radius_without_replacing_depth() -> None:
    row = {"geometry_valid": True, "camera_xyz_m": [0.4, 0.0, 0.12], "width_m": 0.04}
    result = attach_supervised_base_candidate(
        row, t_base_camera=np.eye(4), pose_blockers=[], bottle_diameter_m=0.063
    )
    np.testing.assert_allclose(result["base_xyz_m"], [0.4315, 0.0, 0.12])
    assert result["width_m"] == 0.04
    assert result["camera_xyz_m"] == row["camera_xyz_m"]
    assert result["center_diameter_source"] == "operator_measured_bottle"
    assert not attach_supervised_base_candidate(
        {**row, "geometry_valid": False}, t_base_camera=np.eye(4),
        pose_blockers=[], bottle_diameter_m=0.063,
    )["supervised_base_candidate_valid"]
    for invalid in (float("nan"), -0.063, 0, 0.08):
        assert not attach_supervised_base_candidate(
            row, t_base_camera=np.eye(4), pose_blockers=[], bottle_diameter_m=invalid,
        )["supervised_base_candidate_valid"]


def test_observations_are_left_ordered_and_use_robust_mask_xyz() -> None:
    config, frame, candidates = _scene()

    rows = build_candidate_observations(
        frame,
        candidates,
        config,
        now_monotonic_ns=1_100_000_000,
        upright_direction_camera=np.asarray([0.0, 1.0, 0.0]),
    )

    assert [row["detection_id"] for row in rows] == [7, 3]
    assert [row["left_ordinal"] for row in rows] == [1, 2]
    assert rows[0]["valid"] is True
    assert rows[0]["camera_observation_valid"] is True
    assert rows[0]["geometry_valid"] is True
    assert rows[0]["camera_xyz_semantics"] == "robust_mask_median_axis_estimate"
    assert rows[0]["pixel_uv"] == [94.5, 159.5]
    np.testing.assert_allclose(rows[0]["camera_xyz_m"], [-0.2255, -0.0805, 0.35])


def test_stale_frame_is_rejected_after_inference() -> None:
    config, frame, candidates = _scene()

    rows = build_candidate_observations(
        frame,
        candidates,
        config,
        now_monotonic_ns=1_000_000_000 + (config.max_frame_age_ms + 1) * 1_000_000,
        upright_direction_camera=np.asarray([0.0, 1.0, 0.0]),
    )

    assert rows[0]["valid"] is False
    assert "frame_stale" in rows[0]["reasons"]


def test_visible_depth_valid_target_remains_camera_valid_without_pose_geometry() -> None:
    config, frame, candidates = _scene()

    rows = build_candidate_observations(
        frame, candidates, config, now_monotonic_ns=1_100_000_000
    )

    assert rows[0]["camera_observation_valid"] is True
    assert rows[0]["geometry_valid"] is False
    assert rows[0]["valid"] is False
    assert rows[0]["geometry_reasons"] == ["width_orientation_unavailable"]
    assert rows[0]["camera_xyz_semantics"] == "robust_mask_median_tracking_only"
    assert rows[0]["pixel_uv_semantics"] == "mask_centroid_tracking_only"


def test_requested_height_during_motion_retains_camera_tracking_evidence() -> None:
    config, frame, candidates = _scene()

    rows = build_candidate_observations(
        frame,
        candidates,
        config,
        now_monotonic_ns=1_100_000_000,
        grasp_height_base_m=0.12,
    )

    assert rows[0]["camera_observation_valid"] is True
    assert rows[0]["geometry_valid"] is False
    assert rows[0]["valid"] is False
    np.testing.assert_allclose(rows[0]["camera_xyz_m"], [-0.2255, -0.0805, 0.35])
    assert rows[0]["pixel_uv"] == [94.5, 159.5]
    assert rows[0]["camera_xyz_semantics"] == "robust_mask_median_tracking_only"
    assert rows[0]["pixel_uv_semantics"] == "mask_centroid_tracking_only"
    assert rows[0]["base_surface_xyz_m"] is None
    assert rows[0]["geometry_reasons"] == ["grasp_height_transform_unavailable"]

    payload = attach_supervised_base_candidate(
        rows[0],
        t_base_camera=None,
        pose_blockers=(
            "pose_not_stationary",
            "pose_does_not_cover_frame_capture",
            "robot_pose_stale",
        ),
    )
    assert payload["camera_xyz_m"] is not None
    assert payload["pixel_uv"] is not None
    assert payload["base_xyz_m"] is None
    assert payload["supervised_base_candidate_valid"] is False


def test_requested_base_height_selects_supported_band_and_matching_pixel() -> None:
    config, frame, candidates = _scene()
    t_base_camera = np.eye(4)
    t_base_camera[:3, :3] = np.asarray([
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ])

    rows = build_candidate_observations(
        frame,
        candidates,
        config,
        now_monotonic_ns=1_100_000_000,
        upright_direction_camera=np.asarray([0.0, 1.0, 0.0]),
        t_base_camera=t_base_camera,
        grasp_height_base_m=-0.04,
        grasp_height_half_band_m=0.005,
    )

    selected = rows[0]
    assert selected["geometry_valid"] is True
    assert selected["grasp_height_base_m"] == -0.04
    assert selected["height_band_body_points"] >= 20
    assert selected["height_band_silhouette_points"] >= 20
    u, v = (int(value) for value in selected["pixel_uv"])
    np.testing.assert_allclose(selected["camera_xyz_m"], frame.xyz_camera_m[v, u])
    point_base = t_base_camera @ np.asarray([*selected["camera_xyz_m"], 1.0])
    assert abs(point_base[2] - (-0.04)) <= 0.005
    payload = attach_supervised_base_candidate(
        selected, t_base_camera=t_base_camera, pose_blockers=()
    )
    assert payload["supervised_base_candidate_valid"] is True
    assert payload["base_xyz_m"] is not None


def test_requested_base_height_without_depth_support_fails_geometry_only() -> None:
    config, frame, candidates = _scene()
    t_base_camera = np.eye(4)
    t_base_camera[:3, :3] = np.asarray([
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ])

    rows = build_candidate_observations(
        frame,
        candidates,
        config,
        now_monotonic_ns=1_100_000_000,
        upright_direction_camera=np.asarray([0.0, 1.0, 0.0]),
        t_base_camera=t_base_camera,
        grasp_height_base_m=0.20,
        grasp_height_half_band_m=0.005,
    )

    assert rows[0]["camera_observation_valid"] is True
    assert rows[0]["geometry_valid"] is False
    np.testing.assert_allclose(rows[0]["camera_xyz_m"], [-0.2255, -0.0805, 0.35])
    assert rows[0]["pixel_uv"] == [94.5, 159.5]
    assert rows[0]["camera_xyz_semantics"] == "robust_mask_median_tracking_only"
    assert rows[0]["base_surface_xyz_m"] is None
    assert "grasp_height_band_insufficient" in rows[0]["geometry_reasons"]

    payload = attach_supervised_base_candidate(
        rows[0], t_base_camera=t_base_camera, pose_blockers=()
    )
    assert payload["base_xyz_m"] is None
    assert payload["supervised_base_candidate_valid"] is False


def test_zero_depth_never_produces_camera_tracking_xyz() -> None:
    config, frame, candidates = _scene()
    empty_xyz = np.full_like(frame.xyz_camera_m, np.nan)
    frame = RgbdFrame(
        sequence=frame.sequence,
        monotonic_ns=frame.monotonic_ns,
        camera_serial=frame.camera_serial,
        rgb=frame.rgb,
        depth_m=empty_xyz[..., 2],
        xyz_camera_m=empty_xyz,
    )

    rows = build_candidate_observations(
        frame,
        candidates,
        config,
        now_monotonic_ns=1_100_000_000,
        grasp_height_base_m=0.12,
    )

    assert rows[0]["camera_observation_valid"] is False
    assert rows[0]["camera_xyz_m"] is None
    assert rows[0]["pixel_uv"] == [94.5, 159.5]
    assert "depth_points_insufficient" in rows[0]["camera_reasons"]


def test_locked_target_loss_does_not_fall_back_to_another_bottle() -> None:
    config, frame, candidates = _scene()
    rows = build_candidate_observations(
        frame,
        candidates,
        config,
        now_monotonic_ns=1_100_000_000,
        upright_direction_camera=np.asarray([0.0, 1.0, 0.0]),
    )

    assert find_locked_observation(rows, detection_id=99) is None
    assert find_locked_observation(rows, detection_id=7)["left_ordinal"] == 1


def test_observer_cli_is_camera_denied_by_default() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/vision/observe_grasp_bottle.py", "--ordinal", "1"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["reason"] == "camera_access_not_authorized"
    assert payload["robot_control_enabled"] is False


def test_observer_cli_exposes_separate_camera_start_timeout() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/vision/observe_grasp_bottle.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--camera-start-timeout-s" in completed.stdout


def test_tcp_pose_is_not_silently_used_as_flange_pose() -> None:
    tcp_only = {
        "tcp_position_m": [0.1, 0.2, 0.3],
        "tcp_euler_rad": [0.0, 0.0, 0.0],
        "ts": 123,
    }

    try:
        require_flange_pose(tcp_only)
    except ValueError as error:
        assert str(error) == "flange_pose_required_tcp_pose_rejected"
    else:
        raise AssertionError("TCP pose must not be treated as flange pose")


def test_explicit_flange_pose_is_accepted() -> None:
    position, euler = require_flange_pose({
        "flange_position_m": [0.1, 0.2, 0.3],
        "flange_euler_rad": [0.0, 0.1, 0.2],
    })

    assert position == (0.1, 0.2, 0.3)
    assert euler == (0.0, 0.1, 0.2)


def _shape_candidate(mask: np.ndarray) -> MaskCandidate:
    return MaskCandidate(
        detection_id=4,
        label="bottle",
        score=0.9,
        bbox_xyxy=(0, 0, 100, 100),
        mask=mask,
        authorized=False,
        reasons=("bottle_aspect_out_of_range", "container_type_not_bottle"),
    )


def test_rotated_long_mask_passes_observer_local_aspect_gate() -> None:
    config = VisionConfig.from_yaml("configs/vision.yaml")
    mask = np.zeros((240, 320), dtype=np.uint8)
    box = cv2.boxPoints(((160, 120), (30, 110), 36)).astype(np.int32)
    cv2.fillConvexPoly(mask, box, 1)

    candidate, ratio, recovered = apply_rotated_mask_aspect_gate(
        _shape_candidate(mask.astype(bool)), config
    )

    assert recovered is True
    assert candidate.authorized is True
    assert 3.5 < ratio < 3.8


def test_round_mask_stays_rejected_by_rotated_aspect_gate() -> None:
    config = VisionConfig.from_yaml("configs/vision.yaml")
    mask = np.zeros((240, 320), dtype=np.uint8)
    cv2.circle(mask, (160, 120), 35, 1, -1)

    candidate, ratio, recovered = apply_rotated_mask_aspect_gate(
        _shape_candidate(mask.astype(bool)), config
    )

    assert recovered is False
    assert candidate.authorized is False
    assert ratio < config.min_bottle_aspect_ratio


def test_short_rotated_mask_stays_rejected() -> None:
    config = VisionConfig.from_yaml("configs/vision.yaml")
    mask = np.zeros((240, 320), dtype=np.uint8)
    box = cv2.boxPoints(((160, 120), (55, 75), 48)).astype(np.int32)
    cv2.fillConvexPoly(mask, box, 1)

    candidate, ratio, recovered = apply_rotated_mask_aspect_gate(
        _shape_candidate(mask.astype(bool)), config
    )

    assert recovered is False
    assert candidate.authorized is False
    assert ratio < config.min_bottle_aspect_ratio


def test_capture_wall_time_is_derived_from_monotonic_age() -> None:
    assert capture_wall_time_ms(
        captured_monotonic_ns=1_000_000_000,
        now_monotonic_ns=1_250_000_000,
        now_wall_ms=10_000,
    ) == 9_750


def test_final_postprocessing_age_can_invalidate_observation() -> None:
    row = {"valid": True, "reason": None, "reasons": [], "frame_age_ms": 100.0}

    result = finalize_observation_freshness(
        row,
        captured_monotonic_ns=1_000_000_000,
        now_monotonic_ns=1_301_000_000,
        max_frame_age_ms=300,
    )

    assert result["valid"] is False
    assert result["reason"] == "frame_stale_after_postprocessing"
    assert result["final_frame_age_ms"] == 301.0


def test_transverse_width_uses_near_surface_and_known_upright_axis() -> None:
    y, x = np.meshgrid(
        np.linspace(-0.09, 0.09, 80),
        np.linspace(-0.025, 0.025, 30),
    )
    points = np.column_stack((x.ravel(), y.ravel(), np.full(x.size, 0.4)))

    width = robust_transverse_width_m(
        points,
        points,
        upright_direction_camera=np.asarray([0.0, 1.0, 0.0]),
    )

    assert 0.048 < width < 0.052


def test_transverse_width_requires_an_upright_axis_projection() -> None:
    points = np.zeros((100, 3))
    assert robust_transverse_width_m(
        points,
        points,
        upright_direction_camera=np.asarray([0.0, 0.0, 1.0]),
    ) is None


def test_center_estimate_advances_half_width_away_from_camera_in_base_xy() -> None:
    center = estimate_base_center_from_surface(
        surface_xyz_m=[1.0, 0.0, 0.2],
        camera_origin_xyz_m=[0.0, 0.0, 0.5],
        width_m=0.06,
    )

    np.testing.assert_allclose(center, [1.03, 0.0, 0.2])


def test_saved_l2_width_fixture_matches_full_geometry_within_one_centimeter() -> None:
    root = Path("artifacts/vision/observer/l2-width-fixture-20260908")
    with np.load(root / "frame-mask.npz", allow_pickle=False) as stored:
        xyz = stored["xyz_camera_m"]
        mask = stored["mask"]
        upright = stored["upright_direction_camera"]
    config = VisionConfig.from_yaml("configs/vision.yaml")
    from thirdhand_va.vision.geometry.pointcloud import erode_mask, robust_mask_points

    body, _ = robust_mask_points(
        xyz,
        erode_mask(mask, radius=config.mask_erosion_px),
        min_depth_m=config.min_depth_m,
        max_depth_m=config.max_depth_m,
        mad_scale=3.5,
    )
    silhouette, _ = robust_mask_points(
        xyz,
        mask,
        min_depth_m=config.min_depth_m,
        max_depth_m=config.max_depth_m,
        mad_scale=3.5,
    )

    width = robust_transverse_width_m(
        body, silhouette, upright_direction_camera=upright
    )

    assert abs(width - 0.06384390008800797) < 0.01


def test_real_l2_producer_motion_contract_fixture_is_fail_closed() -> None:
    source = Path(
        "tests/fixtures/integration/observer-producer-motion-contract.jsonl"
    )
    rows = [json.loads(line) for line in source.read_text().splitlines()]

    assert [row["scenario"] for row in rows] == [
        "stationary_initial_height_band_valid",
        "motion_camera_tracking_only",
        "idle_old_inflight_camera_tracking_only",
        "stationary_new_height_band_valid",
    ]
    for row in (rows[0], rows[3]):
        assert row["calibration_id"].startswith("sha256:")
        assert row["handeye"]["calibration_id"] == row["calibration_id"]
        assert row["camera_observation_valid"] is True
        assert row["geometry_valid"] is True
        assert row["supervised_base_candidate_valid"] is True
        assert row["base_xyz_m"] is not None
    for row in (rows[1], rows[2]):
        assert row["camera_observation_valid"] is True
        assert row["camera_xyz_m"] is not None
        assert row["pixel_uv"] is not None
        assert row["camera_xyz_semantics"] == "robust_mask_median_tracking_only"
        assert row["geometry_valid"] is False
        assert row["valid"] is False
        assert row["supervised_base_candidate_valid"] is False
        assert row["base_xyz_m"] is None


def test_real_l2_fixed_z_producer_contract_separates_xy_from_plan_z() -> None:
    source = Path(
        "tests/fixtures/integration/observer-producer-fixed-z-contract.jsonl"
    )
    rows = [json.loads(line) for line in source.read_text().splitlines()]

    assert [row["scenario"] for row in rows] == [
        "fixed_z_stationary_initial_axis_valid",
        "fixed_z_motion_camera_tracking_only",
        "fixed_z_idle_old_inflight_camera_tracking_only",
        "fixed_z_stationary_new_axis_valid",
    ]
    for row in (rows[0], rows[3]):
        assert row["camera_xyz_semantics"] == "robust_mask_median_axis_estimate"
        assert row["geometry_valid"] is True
        assert row["supervised_base_candidate_valid"] is True
        assert row["calibration_id"] == row["handeye"]["calibration_id"]
        assert row["plan_input_grasp_xyz_m"][:2] == row["base_xyz_m"][:2]
        assert row["plan_input_grasp_xyz_m"][2] == 0.13
        assert row["base_xyz_m"][2] != 0.13
    for row in (rows[1], rows[2]):
        assert row["camera_observation_valid"] is True
        assert row["camera_xyz_semantics"] == "robust_mask_median_tracking_only"
        assert row["camera_xyz_m"] is not None
        assert row["geometry_valid"] is False
        assert row["supervised_base_candidate_valid"] is False
        assert row["base_xyz_m"] is None
        assert row["plan_input_grasp_xyz_m"] is None
