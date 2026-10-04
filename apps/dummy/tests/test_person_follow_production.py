import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.person_follow.contracts import MotionProposal, VisionObservation
from dummy.person_follow.controller import JacobianController
from dummy.person_follow.jacobian import LocalVisualJacobian
from dummy.person_follow.logging import JsonlEventLogger
from dummy.person_follow.proposal import ProposalFactory
from dummy.person_follow.session import FollowSession, FollowState
from dummy.person_follow.verifier import MoveVerifier
from dummy.gateway.ownership import LeaseRegistry
from dummy.gateway.policy import GatewayPolicy
from dummy.gateway.protocol import validate_request


def observation(**overrides):
    values = dict(
        schema_version="1.0",
        frame_id="f-1",
        captured_at=10.0,
        camera_view_id="front-pinhole",
        calibration_hash="cam-sha",
        model_id="rtmdet-tiny",
        model_sha256="model-sha",
        identity_id="person-1",
        identity_state="LOCKED",
        center_px=(350.0, 220.0),
        bbox_xyxy=(300.0, 100.0, 400.0, 400.0),
        confidence=0.92,
        latency_ms=12.0,
    )
    values.update(overrides)
    return VisionObservation(**values)


def test_observation_rejects_nonfinite_and_invalid_box():
    with pytest.raises(ValueError):
        observation(center_px=(math.nan, 1.0))
    with pytest.raises(ValueError):
        observation(bbox_xyxy=(10, 10, 5, 20))


def test_jsonl_logger_always_emits_stable_fields(tmp_path):
    path = tmp_path / "events.jsonl"
    JsonlEventLogger(path, "dummy").emit("session_started", run_id="r1")
    event = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "timestamp_utc", "monotonic_ns", "level", "component", "event",
        "run_id", "session_id", "frame_id", "identity_id", "proposal_id",
        "request_id", "state_before", "state_after", "reason_code", "latency_ms",
    }
    assert required <= event.keys()
    assert event["run_id"] == "r1"
    assert event["identity_id"] is None


def test_session_fails_closed_on_stale_or_ambiguous_observation():
    session = FollowSession("s1", max_observation_age_s=0.5)
    assert session.accept(observation(), now=10.1) == FollowState.LOCKED
    assert session.can_propose
    assert session.accept(observation(captured_at=9.0), now=10.1) == FollowState.HOLDING
    assert not session.can_propose
    assert session.accept(observation(identity_state="AMBIGUOUS"), now=10.1) == FollowState.HOLDING


def test_measured_jacobian_reduces_error_with_bounded_step():
    dq = np.array([[0.2, 0.0], [-0.2, 0.0], [0.0, 0.2], [0.0, -0.2]])
    true_j = np.array([[20.0, 1.0], [2.0, 15.0]])
    de = dq @ true_j.T
    model = LocalVisualJacobian.fit(dq, de, calibration_hash="cal-sha")
    controller = JacobianController(model, gain=0.5, max_step_deg=(0.5, 0.5), deadband_px=2.0)
    step = controller.compute((30.0, -20.0))
    assert max(abs(v) for v in step) <= 0.5
    predicted = np.array([30.0, -20.0]) + model.matrix @ np.array(step)
    assert np.linalg.norm(predicted) < np.linalg.norm([30.0, -20.0])


def test_proposal_is_fresh_single_use_and_bound_to_identity():
    factory = ProposalFactory(max_age_s=0.25)
    proposal = factory.create("s1", observation(), (0.2, -0.1), now=10.1)
    assert proposal.identity_id == "person-1"
    assert proposal.is_fresh(10.2)
    assert not proposal.is_fresh(10.5)


def test_verifier_requires_same_identity_and_progress():
    verifier = MoveVerifier(min_improvement_px=1.0)
    before = observation(center_px=(350.0, 220.0))
    after = observation(frame_id="f-2", center_px=(340.0, 230.0), captured_at=10.2)
    result = verifier.verify(before, after, target_px=(320.0, 240.0))
    assert result.ok
    wrong = verifier.verify(before, observation(identity_id="person-2"), target_px=(320.0, 240.0))
    assert not wrong.ok and wrong.reason_code == "IDENTITY_CHANGED"


def test_gateway_protocol_and_policy_reject_replay_raw_and_expired():
    registry = LeaseRegistry(ttl_s=1.0)
    lease = registry.acquire("s1", now=1.0)
    proposal = MotionProposal(
        schema_version="1.0", proposal_id="p1", session_id="s1",
        identity_id="person-1", frame_id="f1", calibration_hash="cal-sha",
        created_at=1.0, expires_at=1.2, joints_deg=(0.2, -0.1),
    )
    request = {"cmd": "execute_proposal", "request_id": "r1", "lease_id": lease.lease_id,
               "proposal": proposal.to_dict()}
    parsed = validate_request(request)
    policy = GatewayPolicy(max_step_deg=0.75)
    first = policy.authorize(parsed, registry, current_joints=(0.0, 0.0), now=1.1)
    assert first.ok
    assert not policy.authorize(parsed, registry, current_joints=(0.0, 0.0), now=1.1).ok
    assert not GatewayPolicy().authorize_command({"cmd": "set_joint_raw"}).ok
    expired = dict(request)
    expired["request_id"] = "r2"
    expired["proposal"] = dict(request["proposal"], proposal_id="p2")
    assert not policy.authorize(validate_request(expired), registry, (0.0, 0.0), now=2.0).ok
