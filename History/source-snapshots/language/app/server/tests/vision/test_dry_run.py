from __future__ import annotations

import json

import numpy as np
import pytest

from vision.dry_run import build_dry_run_report, generate_top_down_candidates
from vision.types import CalibrationRef, FrameStamp, PoseEstimate, TrackState
from test_safety import calibration, cloud, safety_config, target


def test_top_down_candidate_is_deterministic_when_cloud_order_changes():
    config = safety_config()
    first = generate_top_down_candidates(cloud(), table_plane_z_m=0.08, config=config)
    second = generate_top_down_candidates(cloud()[::-1], table_plane_z_m=0.08, config=config)
    assert len(first) == len(second) == 1
    np.testing.assert_allclose(first[0].grasp_xyz_m, second[0].grasp_xyz_m)
    np.testing.assert_allclose(first[0].pregrasp_xyz_m, second[0].pregrasp_xyz_m)
    assert first[0].width_m == pytest.approx(second[0].width_m)
    assert first[0].score == pytest.approx(second[0].score)


def test_top_down_candidate_obeys_table_clearance_and_width_limit():
    candidate = generate_top_down_candidates(
        cloud(), table_plane_z_m=0.14, config=safety_config()
    )[0]
    assert candidate.grasp_xyz_m[2] >= 0.15
    assert candidate.pregrasp_xyz_m[2] > candidate.grasp_xyz_m[2]
    assert candidate.retreat_xyz_m[2] > candidate.grasp_xyz_m[2]
    assert 0.01 <= candidate.width_m <= 0.12


def test_valid_scenario_produces_manual_review_eligible_report():
    report = build_dry_run_report(
        target=target(),
        target_cloud_m=cloud(),
        calibration=calibration(),
        now_ns=200,
        config=safety_config(),
        table_plane_z_m=0.08,
        reachable=True,
        collision_free=True,
    )
    assert report.approved
    assert report.reasons == ()
    assert report.candidate_xyz_m is not None
    assert report.score is not None


@pytest.mark.parametrize(
    "reachable,collision_free,expected",
    [
        (False, True, "target_not_reachable"),
        (True, False, "no_collision_free_candidate"),
    ],
)
def test_dry_run_fails_closed_without_reachability_or_collision_clearance(
    reachable, collision_free, expected
):
    report = build_dry_run_report(
        target(),
        cloud(),
        calibration(),
        200,
        safety_config(),
        0.08,
        reachable,
        collision_free,
    )
    assert not report.approved
    assert expected in report.reasons
    assert report.candidate_xyz_m is None


def test_empty_or_overwide_cloud_has_no_candidate():
    assert generate_top_down_candidates(np.empty((0, 3)), 0.08, safety_config()) == ()
    wide = np.column_stack(
        (
            np.linspace(0.2, 0.6, 40),
            np.linspace(-0.3, 0.3, 40),
            np.linspace(0.1, 0.2, 40),
        )
    )
    assert generate_top_down_candidates(wide, 0.08, safety_config()) == ()


def test_report_schema_contains_no_transport_or_execution_instructions():
    report = build_dry_run_report(
        target(), cloud(), calibration(), 200, safety_config(), 0.08, True, True
    )
    payload = report.to_dict()
    encoded = json.dumps(payload, sort_keys=True).lower()
    assert set(payload) == {
        "approved",
        "reasons",
        "candidate_xyz_m",
        "score",
        "target_track_id",
        "calibration_id",
    }
    for forbidden in ("command_complete", "websocket", "can_frame", "move_joints", "set_gripper"):
        assert forbidden not in encoded
