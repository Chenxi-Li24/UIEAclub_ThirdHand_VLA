from types import SimpleNamespace

import numpy as np
import pytest

from thirdhand_va.vision import supervised_nearfield as bridge


@pytest.fixture
def scene(monkeypatch):
    frame = SimpleNamespace(sequence=7, monotonic_ns=9_900_000_000)
    payload = {"target_id": "detection:0", "calibration_id": "cal",
               "observed_at_ms": 9900, "robot_state_ts": 9950,
               "robot_pose_blockers": [], "camera_xyz_m": None}
    pose = {"trial_id": "trial", "controller_phase": "descend",
            "tcp_position_m": [.4, 0, .13], "tcp_euler_rad": [0, .8, .49],
            "supervised_anchor": {
                "anchor_id": "anchor", "trial_id": "trial",
                "target_id": "detection:0", "calibration_id": "cal",
                "approved_at_ms": 9000, "base_xyz_m": [.4, 0, .12],
                "reference": {"fake_test_geometry": True}}}
    def evaluate(frame, candidate, transform, reference, translation):
        return {"rgb_observation_valid": candidate is not None,
                "projection_guard_valid": transform is not None and candidate is not None,
                "guard_blockers": (["target_lost"] if candidate is None else [])
                                   + (["pose_unavailable"] if transform is None else []),
                "diagnostics": {"expected_center_camera_xyz_m": [0, 0, .07],
                                "expected_center_uv": [320, 240]}}
    monkeypatch.setattr(bridge, "evaluate_reference", evaluate)
    return dict(payload=payload, frame=frame, candidate=object(), pose=pose,
                t_base_camera=np.eye(4), now_ms=10000)


def test_rgb_guard_does_not_invent_missing_depth(scene):
    result = bridge.build_projection_observation(**scene)
    assert result["projection_guard_valid"]
    assert result["raw_depth_used"] is False
    assert "camera_xyz_m" not in result
    assert result["projected_anchor_camera_xyz_m"] == [0, 0, .07]


def test_reference_candidate_preserves_final_watch_identity(monkeypatch):
    monkeypatch.setattr(bridge, "create_reference", lambda *args: {"schema": "reference"})
    payload = {
        "supervised_base_candidate_valid": True,
        "base_xyz_m": [0.4, 0.0, 0.12],
        "calibration_id": "cal",
        "target_id": "detection:0",
        "frame_id": 7,
        "observed_at_ms": 9900,
        "camera_xyz_m": [0.0, 0.0, 0.2],
        "pixel_uv": [320.0, 210.0],
        "track_state": "locked",
        "locked_detection_id": 0,
        "requested_ordinal": 1,
    }

    result = bridge.add_reference_candidate(
        payload,
        frame=object(),
        candidate=object(),
        t_base_camera=np.eye(4),
        observation_height_m=0.12,
        bottle_diameter_m=0.063,
    )

    reference = result["nearfield_reference_candidate"]
    assert reference["track_state"] == "locked"
    assert reference["locked_detection_id"] == 0
    assert reference["requested_ordinal"] == 1


@pytest.mark.parametrize("change", ["lost", "stale", "trial", "target", "calibration", "expired"])
def test_failures_block_projection_and_rgb(scene, change):
    if change == "lost":
        scene["candidate"] = None
    elif change == "stale":
        scene["now_ms"] = 10201
    elif change == "expired":
        scene["pose"]["supervised_anchor"]["approved_at_ms"] = -400000
    else:
        key = {"trial": "trial_id", "target": "target_id", "calibration": "calibration_id"}[change]
        scene["pose"]["supervised_anchor"][key] = "wrong"
    result = bridge.build_projection_observation(**scene)
    assert not result["projection_guard_valid"]
    assert not result["rgb_observation_valid"]


def test_anchor_age_is_valid_through_five_minutes_without_renewal(scene):
    anchor = scene["pose"]["supervised_anchor"]
    anchor["approved_at_ms"] = 9_000
    scene["now_ms"] = 309_000
    scene["payload"]["observed_at_ms"] = 308_900

    at_boundary = bridge.build_projection_observation(**scene)

    assert "anchor_expired" not in at_boundary["guard_blockers"]
    assert at_boundary["projection_guard_valid"] is True
    scene["now_ms"] = 309_001
    scene["payload"]["observed_at_ms"] = 308_901

    beyond_boundary = bridge.build_projection_observation(**scene)

    assert "anchor_expired" in beyond_boundary["guard_blockers"]
    assert beyond_boundary["projection_guard_valid"] is False
    assert anchor["approved_at_ms"] == 9_000


def test_motion_rgb_cannot_authorize_static_projection(scene):
    scene["t_base_camera"] = None
    scene["payload"]["robot_pose_blockers"] = ["pose_not_stationary"]
    result = bridge.build_projection_observation(**scene)
    assert result["rgb_observation_valid"]
    assert not result["projection_guard_valid"]


def test_contact_reference_follows_lift_but_rejects_rotation(scene):
    scene["pose"]["supervised_anchor"]["attachment"] = {
        "contact_tcp_position_m": [.4, 0, .13],
        "contact_tcp_euler_rad": [0, .8, .49],
        "contact_verified_at_ms": 9950,
    }
    scene["pose"]["tcp_position_m"][2] += .08
    result = bridge.build_projection_observation(**scene)
    np.testing.assert_allclose(result["expected_anchor_base_xyz_m"], [.4, 0, .20])
    assert result["projection_guard_valid"]
    scene["pose"]["tcp_euler_rad"][1] += .2
    assert not bridge.build_projection_observation(**scene)["projection_guard_valid"]


def test_malformed_projection_reference_fails_closed(scene, monkeypatch):
    def broken(*args):
        raise ValueError("bad reference")
    monkeypatch.setattr(bridge, "evaluate_reference", broken)
    result = bridge.build_projection_observation(**scene)
    assert not result["projection_guard_valid"]
    assert result["guard_blockers"] == ["projection_reference_invalid"]
