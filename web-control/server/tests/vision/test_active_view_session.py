from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from vision.active_view_session import (
    ActiveViewPhase,
    ActiveViewSession,
    ActiveViewSessionCoordinator,
    Cancel,
    DepthObserved,
    DepthStabilityWindow,
    EvidenceExpired,
    IdentityObserved,
    InvalidTransition,
    MoveCompleted,
    MoveStarted,
    OperatorConfirmed,
    ProposalReady,
    Settled,
)
from vision.active_view_types import DepthQuality, ObservationMoveProposal
from vision.types import FrameStamp, PoseEstimate
from vision_models.active_view_online import load_active_view_config


PROJECT_ROOT = Path(__file__).parents[4]
EVIDENCE_ID = "sha256:" + "a" * 64
SESSION_ID = "11111111-1111-4111-8111-111111111111"
PROPOSAL_ID = "22222222-2222-4222-8222-222222222222"
REQUEST_ID = "33333333-3333-4333-8333-333333333333"


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


def authorize_move(
    session: ActiveViewSession,
    session_id: str,
    observed_ns: int = 105,
) -> ActiveViewSession:
    return session.transition(
        OperatorConfirmed(session_id, "proposal-1", observed_ns),
        config(),
    )


def acquiring_session() -> ActiveViewSession:
    session = ActiveViewSession.start("session-1", 9, (EVIDENCE_ID,), 100)
    session = session.transition(ProposalReady("session-1", coarse_proposal()), config())
    session = authorize_move(session, "session-1")
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
    session = authorize_move(session, "current")
    session = session.transition(MoveStarted("current", "request-1", 110), config())
    session = session.transition(MoveCompleted("current", "request-1", 120), config())
    session = session.transition(Settled("current", 130), config())
    aborted = session.transition(IdentityObserved("current", 10, True, 140), config())

    assert aborted.phase is ActiveViewPhase.ABORTED
    assert aborted.reasons == ("target_identity_changed",)


def test_movement_advances_only_with_matching_completion_and_settle_events() -> None:
    session = ActiveViewSession.start("session-1", 9, (EVIDENCE_ID,), 100)
    session = session.transition(ProposalReady("session-1", coarse_proposal()), config())
    session = authorize_move(session, "session-1")
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
    session = authorize_move(session, "expiry")
    expired = session.transition(MoveStarted("expiry", "request-1", 110), config())
    assert expired.phase is ActiveViewPhase.ABORTED
    assert expired.reasons == ("proposal_expired",)

    verifying = ActiveViewSession.start("identity", 9, (EVIDENCE_ID,), 100)
    verifying = verifying.transition(ProposalReady("identity", coarse_proposal()), config())
    verifying = authorize_move(verifying, "identity")
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
        "ActiveViewSessionCoordinator",
        "DepthStabilityWindow",
        "InvalidTransition",
        "OperatorConfirmed",
    }
    assert expected <= set(vision.__all__)
    assert vision.ActiveViewSession is ActiveViewSession


def test_move_requires_confirmation_of_the_current_proposal() -> None:
    session = ActiveViewSession.start(SESSION_ID, 9, (EVIDENCE_ID,), 100)
    session = session.transition(ProposalReady(SESSION_ID, coarse_proposal()), config())

    with pytest.raises(InvalidTransition, match="OperatorConfirmed"):
        session.transition(MoveStarted(SESSION_ID, REQUEST_ID, 110), config())

    authorized = session.transition(
        OperatorConfirmed(SESSION_ID, PROPOSAL_ID, 105),
        config(),
    )
    assert authorized.phase is ActiveViewPhase.MOVE_AUTHORIZED
    moving = authorized.transition(MoveStarted(SESSION_ID, REQUEST_ID, 110), config())
    assert moving.phase is ActiveViewPhase.MOVING_TO_VIEW


def test_coordinator_emits_evidence_bound_proposal_and_execution_locked_state() -> None:
    coordinator = ActiveViewSessionCoordinator(
        config(),
        evidence_ids=(EVIDENCE_ID,),
        proposal_id_factory=lambda: PROPOSAL_ID,
    )
    started = coordinator.handle_command(
        {"type": "active_view_start", "session_id": SESSION_ID, "identity_id": 9},
        now_ns=100,
    )
    proposal_events = coordinator.offer_proposal(coarse_proposal(), now_ns=101)

    assert started[-1]["phase"] == "target_locked"
    proposal = next(event for event in proposal_events if event["type"] == "active_view_move_proposal")
    assert proposal["proposal_id"] == PROPOSAL_ID
    assert proposal["session_id"] == SESSION_ID
    assert proposal["evidence_ids"] == [EVIDENCE_ID]
    assert proposal["joints_deg"] == [0.0] * 6
    assert proposal["robot_execution_enabled"] is False
    assert proposal["active_view_execution_enabled"] is False


def test_coordinator_rejects_wrong_proposal_duplicate_completion_and_old_session() -> None:
    coordinator = ActiveViewSessionCoordinator(
        config(),
        evidence_ids=(EVIDENCE_ID,),
        proposal_id_factory=lambda: PROPOSAL_ID,
    )
    coordinator.handle_command(
        {"type": "active_view_start", "session_id": SESSION_ID, "identity_id": 9},
        now_ns=100,
    )
    coordinator.offer_proposal(coarse_proposal(), now_ns=101)
    wrong = coordinator.handle_command(
        {
            "type": "active_view_operator_confirmed",
            "session_id": SESSION_ID,
            "proposal_id": "44444444-4444-4444-8444-444444444444",
        },
        now_ns=105,
    )
    assert wrong[-1]["phase"] == "aborted"
    assert "proposal" in " ".join(wrong[-1]["reasons"])

    fresh = ActiveViewSessionCoordinator(
        config(),
        evidence_ids=(EVIDENCE_ID,),
        proposal_id_factory=lambda: PROPOSAL_ID,
    )
    fresh.handle_command(
        {"type": "active_view_start", "session_id": SESSION_ID, "identity_id": 9},
        now_ns=100,
    )
    fresh.offer_proposal(coarse_proposal(), now_ns=101)
    fresh.handle_command(
        {"type": "active_view_operator_confirmed", "session_id": SESSION_ID, "proposal_id": PROPOSAL_ID},
        now_ns=105,
    )
    fresh.handle_command(
        {
            "type": "active_view_motion_started",
            "session_id": SESSION_ID,
            "proposal_id": PROPOSAL_ID,
            "request_id": REQUEST_ID,
        },
        now_ns=110,
    )
    fresh.handle_command(
        {"type": "active_view_motion_completed", "session_id": SESSION_ID, "request_id": REQUEST_ID},
        now_ns=120,
    )
    duplicate = fresh.handle_command(
        {"type": "active_view_motion_completed", "session_id": SESSION_ID, "request_id": REQUEST_ID},
        now_ns=121,
    )
    assert duplicate[-1]["phase"] == "aborted"

    old = fresh.handle_command(
        {
            "type": "active_view_cancel",
            "session_id": "55555555-5555-4555-8555-555555555555",
        },
        now_ns=122,
    )
    assert old[-1]["type"] == "active_view_protocol_rejected"
