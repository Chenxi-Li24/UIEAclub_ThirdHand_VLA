from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from vision.active_view_session import (
    ActiveViewPhase,
    ActiveViewSession,
    Cancel,
    DepthObserved,
    DepthStabilityWindow,
    EvidenceExpired,
    IdentityObserved,
    InvalidTransition,
    MoveCompleted,
    MoveStarted,
    ProposalReady,
    Settled,
)
from vision.active_view_types import DepthQuality, ObservationMoveProposal
from vision.types import FrameStamp, PoseEstimate
from vision_models.active_view_online import load_active_view_config


PROJECT_ROOT = Path(__file__).parents[4]
EVIDENCE_ID = "sha256:" + "a" * 64


def config():
    return load_active_view_config(PROJECT_ROOT / "configs/vision/active_view.yaml")


def coarse_proposal() -> ObservationMoveProposal:
    return ObservationMoveProposal.coarse(
        identity_id=9,
        source_stamp=FrameStamp("lumos_rgb", 1, 100),
        expires_ns=1_000,
        target_pose_id="table_center",
        joints_deg=np.zeros(6),
        evidence_ids=(EVIDENCE_ID,),
    )


def good_depth_quality(center: np.ndarray | None = None) -> DepthQuality:
    center = np.array([0.2, 0.1, 0.5]) if center is None else np.asarray(center, dtype=float)
    return DepthQuality(
        valid_points=100,
        central_fraction=0.8,
        center_d435_m=center,
        center_base_m=center,
        mad_m=np.array([0.001, 0.001, 0.001]),
        acceptable=True,
        reasons=(),
    )


def poor_depth_quality() -> DepthQuality:
    return DepthQuality(
        valid_points=100,
        central_fraction=0.2,
        center_d435_m=np.array([0.2, 0.1, 0.5]),
        center_base_m=np.array([0.2, 0.1, 0.5]),
        mad_m=np.array([0.001, 0.001, 0.001]),
        acceptable=False,
        reasons=("insufficient_central_coverage",),
    )


def pose(timestamp_ns: int, x_offset_m: float = 0.0) -> PoseEstimate:
    return PoseEstimate(
        xyz_m=np.array([0.2 + x_offset_m, 0.1, 0.5]),
        covariance_m2=np.eye(3) * 1e-6,
        frame="robot_base",
        stamp=FrameStamp("lumos+d435", timestamp_ns, timestamp_ns),
        calibration_id=EVIDENCE_ID,
    )


def acquiring_session() -> ActiveViewSession:
    session = ActiveViewSession.start("session-1", 9, (EVIDENCE_ID,), 100)
    session = session.transition(ProposalReady("session-1", coarse_proposal()), config())
    session = session.transition(MoveStarted("session-1", "request-1", 110), config())
    session = session.transition(MoveCompleted("session-1", "request-1", 120), config())
    session = session.transition(Settled("session-1", 130), config())
    session = session.transition(IdentityObserved("session-1", 9, True, 140), config())
    assert session.phase is ActiveViewPhase.VERIFYING_IDENTITY
    session = session.transition(IdentityObserved("session-1", 9, True, 150), config())
    assert session.phase is ActiveViewPhase.ACQUIRING_DEPTH
    return session


def test_session_requires_completion_settle_two_identities_and_stable_depth() -> None:
    session = acquiring_session()

    for index in range(5):
        timestamp = 151 + index
        session = session.transition(
            DepthObserved(
                "session-1",
                9,
                pose(timestamp, x_offset_m=index * 0.0005),
                good_depth_quality(),
                timestamp,
            ),
            config(),
        )

    assert session.phase is ActiveViewPhase.GRASP_PREVIEW
    assert len(session.depth_samples) == 5
    assert session.reasons == ()


def test_wrong_session_or_identity_cannot_advance_current_session() -> None:
    session = ActiveViewSession.start("current", 9, (EVIDENCE_ID,), 100)
    with pytest.raises(InvalidTransition, match="session"):
        session.transition(IdentityObserved("old", 9, True, 110), config())

    session = session.transition(ProposalReady("current", coarse_proposal()), config())
    session = session.transition(MoveStarted("current", "request-1", 110), config())
    session = session.transition(MoveCompleted("current", "request-1", 120), config())
    session = session.transition(Settled("current", 130), config())
    aborted = session.transition(IdentityObserved("current", 10, True, 140), config())

    assert aborted.phase is ActiveViewPhase.ABORTED
    assert aborted.reasons == ("target_identity_changed",)


def test_movement_advances_only_with_matching_completion_and_settle_events() -> None:
    session = ActiveViewSession.start("session-1", 9, (EVIDENCE_ID,), 100)
    session = session.transition(ProposalReady("session-1", coarse_proposal()), config())
    moving = session.transition(MoveStarted("session-1", "request-1", 110), config())

    with pytest.raises(InvalidTransition, match="MoveCompleted"):
        moving.transition(Settled("session-1", 120), config())
    with pytest.raises(InvalidTransition, match="request"):
        moving.transition(MoveCompleted("session-1", "wrong", 120), config())
    with pytest.raises(InvalidTransition, match="DepthObserved"):
        moving.transition(
            DepthObserved(
                "session-1",
                9,
                pose(120),
                good_depth_quality(),
                120,
            ),
            config(),
        )


def test_proposal_expiry_boundary_and_duplicate_identity_timestamp_fail_closed() -> None:
    expiring = ObservationMoveProposal.coarse(
        identity_id=9,
        source_stamp=FrameStamp("lumos_rgb", 1, 100),
        expires_ns=110,
        target_pose_id="table_center",
        joints_deg=np.zeros(6),
        evidence_ids=(EVIDENCE_ID,),
    )
    session = ActiveViewSession.start("expiry", 9, (EVIDENCE_ID,), 100)
    session = session.transition(ProposalReady("expiry", expiring), config())
    expired = session.transition(MoveStarted("expiry", "request-1", 110), config())
    assert expired.phase is ActiveViewPhase.ABORTED
    assert expired.reasons == ("proposal_expired",)

    verifying = ActiveViewSession.start("identity", 9, (EVIDENCE_ID,), 100)
    verifying = verifying.transition(ProposalReady("identity", coarse_proposal()), config())
    verifying = verifying.transition(MoveStarted("identity", "request-1", 110), config())
    verifying = verifying.transition(MoveCompleted("identity", "request-1", 120), config())
    verifying = verifying.transition(Settled("identity", 130), config())
    verifying = verifying.transition(IdentityObserved("identity", 9, True, 140), config())
    with pytest.raises(InvalidTransition, match="stale"):
        verifying.transition(IdentityObserved("identity", 9, True, 140), config())


def test_unacceptable_depth_requests_refinement_and_enforces_limit() -> None:
    session = acquiring_session()
    refining = session.transition(
        DepthObserved("session-1", 9, pose(151), poor_depth_quality(), 151),
        config(),
    )
    assert refining.phase is ActiveViewPhase.REFINE_VIEW
    assert refining.depth_samples == ()

    exhausted = replace(session, refinement_steps=3).transition(
        DepthObserved("session-1", 9, pose(151), poor_depth_quality(), 151),
        config(),
    )
    assert exhausted.phase is ActiveViewPhase.ABORTED
    assert exhausted.reasons == ("view_refinement_exhausted",)


def test_depth_stability_window_is_bounded_and_uses_median_mad() -> None:
    window = DepthStabilityWindow(5, 0.010, 0.005)
    decision = None
    for index in range(5):
        decision = window.add(9, pose(100 + index, index * 0.001))
        window = replace(window, identity_id=9, samples=decision.samples)

    assert decision is not None
    assert decision.stable is True
    assert len(decision.samples) == 5
    np.testing.assert_allclose(decision.center_m, [0.202, 0.1, 0.5])
    assert np.max(decision.mad_m) <= 0.005


def test_target_jump_calibration_change_cancel_and_expiry_abort() -> None:
    session = acquiring_session()
    session = session.transition(
        DepthObserved("session-1", 9, pose(151), good_depth_quality(), 151),
        config(),
    )
    moved = session.transition(
        DepthObserved("session-1", 9, pose(152, 0.02), good_depth_quality(), 152),
        config(),
    )
    assert moved.phase is ActiveViewPhase.ABORTED
    assert moved.reasons == ("target_moved",)

    expired = acquiring_session().transition(
        EvidenceExpired("session-1", EVIDENCE_ID, 151),
        config(),
    )
    assert expired.phase is ActiveViewPhase.ABORTED
    assert expired.reasons == ("evidence_expired",)

    cancelled = acquiring_session().transition(Cancel("session-1", "operator_stop", 151), config())
    assert cancelled.phase is ActiveViewPhase.ABORTED
    assert cancelled.reasons == ("operator_stop",)
    with pytest.raises(InvalidTransition, match="terminal"):
        cancelled.transition(Cancel("session-1", "again", 152), config())


def test_active_view_session_is_exposed_as_a_public_pure_interface() -> None:
    import vision

    expected = {
        "ActiveViewPhase",
        "ActiveViewSession",
        "DepthStabilityWindow",
        "InvalidTransition",
    }
    assert expected <= set(vision.__all__)
    assert vision.ActiveViewSession is ActiveViewSession
