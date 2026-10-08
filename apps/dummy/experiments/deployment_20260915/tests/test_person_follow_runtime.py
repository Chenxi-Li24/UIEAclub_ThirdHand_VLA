import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.gateway.robot_3000 import Robot3000Adapter, extract_joints
from dummy_legacy.gateway.ownership import LeaseRegistry
from dummy_legacy.person_follow.calibration import CalibrationReport
from dummy_legacy.person_follow.gateway_client import GatewayClient
from dummy_legacy.person_follow.runtime import PersonFollowRuntime


def test_calibration_report_refuses_hash_or_operating_range_mismatch():
    report = CalibrationReport.from_dict({
        "schema_version": "1.0", "calibration_hash": "cal", "camera_calibration_hash": "cam",
        "model_sha256": "model", "joint_names": ["j4", "j5"],
        "jacobian": [[20.0, 1.0], [2.0, 15.0]], "max_step_deg": [0.5, 0.5],
        "operating_min_deg": [-20, -20], "operating_max_deg": [20, 20],
    })
    report.validate("cam", "model", [0, 0])
    with pytest.raises(ValueError):
        report.validate("wrong", "model", [0, 0])
    with pytest.raises(ValueError):
        report.validate("cam", "model", [30, 0])


def test_gateway_client_refuses_direct_robot_port():
    with pytest.raises(ValueError):
        GatewayClient("ws://127.0.0.1:3000/ws")
    assert GatewayClient("ws://127.0.0.1:31023").url.endswith(":31023")


def test_robot_adapter_requires_local_3000_websocket():
    assert Robot3000Adapter("ws://127.0.0.1:3000/ws").url.endswith("3000/ws")
    with pytest.raises(ValueError):
        Robot3000Adapter("ws://10.0.0.2:3000/ws")


def test_robot_adapter_extracts_only_finite_robot_state_joints():
    assert extract_joints({"type": "runtime_status", "joints": [1, 2]}) is None
    assert extract_joints({"type": "robot_state", "joints_deg": [0, 1, 2, 3, 4, 5]}) == (0, 1, 2, 3, 4, 5)
    assert extract_joints({"type": "robot_state", "joints": [0, 1, 2, 3, 4, float("nan")]}) is None


def test_lease_heartbeat_extends_only_matching_owner_and_release_revokes():
    registry = LeaseRegistry(ttl_s=1.0)
    lease = registry.acquire("s1", now=1.0)
    renewed = registry.heartbeat(lease.lease_id, "s1", now=1.5)
    assert renewed.expires_at == 2.5
    with pytest.raises(RuntimeError):
        registry.heartbeat("wrong", "s1", now=1.6)
    assert registry.release(lease.lease_id, "s1")
    assert not registry.valid(lease.lease_id, "s1", now=1.7)


def test_runtime_holds_when_observation_is_stale():
    sent = []

    class FakeGateway:
        async def execute(self, proposal):
            sent.append(proposal)

    runtime = PersonFollowRuntime(FakeGateway(), max_observation_age_s=0.2)
    result = asyncio.run(runtime.handle({"captured_at": 1.0, "identity_state": "LOCKED"}, now=2.0))
    assert result == "HOLDING"
    assert sent == []
