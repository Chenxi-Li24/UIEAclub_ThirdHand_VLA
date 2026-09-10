from dataclasses import FrozenInstanceError

import pytest

from thirdhand_va.common.contracts import ArmState
from thirdhand_va.common.errors import ContractError


def test_arm_state_builds_an_immutable_normalized_contract() -> None:
    state = ArmState.from_message(
        {
            "type": "arm_state",
            "pose_frame": "robot_flange",
            "flange_position_m": [0.4, 0.1, 0.2],
            "flange_euler_rad": [0, 0, 1.5],
            "stationary": True,
            "observed_monotonic_ns": 90,
        },
        received_monotonic_ns=100,
        stationary_since_monotonic_ns=80,
    )

    assert state.pose_frame == "robot_flange"
    assert state.flange_position_m == (0.4, 0.1, 0.2)
    assert state.flange_euler_rad == (0.0, 0.0, 1.5)
    assert state.stationary is True
    assert state.received_monotonic_ns == 100
    assert state.observed_monotonic_ns == 90
    assert state.stationary_since_monotonic_ns == 80
    with pytest.raises(FrozenInstanceError):
        state.stationary = False  # type: ignore[misc]


def test_arm_state_rejects_malformed_or_negative_evidence() -> None:
    with pytest.raises(ContractError, match="expected an arm_state"):
        ArmState.from_message(
            {"type": "other"},
            received_monotonic_ns=1,
            stationary_since_monotonic_ns=1,
        )

    with pytest.raises(ContractError, match="timestamps"):
        ArmState(
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            True,
            -1,
            0,
        )


def test_arm_state_rejects_observation_received_from_the_future() -> None:
    with pytest.raises(ContractError, match="timestamps"):
        ArmState.from_message(
            {
                "type": "arm_state",
                "pose_frame": "robot_flange",
                "flange_position_m": [0.4, 0.1, 0.2],
                "flange_euler_rad": [0.0, 0.0, 0.0],
                "stationary": True,
                "observed_monotonic_ns": 201,
            },
            received_monotonic_ns=200,
            stationary_since_monotonic_ns=190,
        )


@pytest.mark.parametrize("pose_frame", [None, "configured_tool_tcp"])
def test_arm_state_rejects_implicit_or_tool_tcp_semantics(pose_frame) -> None:
    with pytest.raises(ContractError, match="pose_frame must be robot_flange"):
        ArmState.from_message(
            {
                "type": "arm_state",
                "pose_frame": pose_frame,
                "flange_position_m": [0.4, 0.1, 0.2],
                "flange_euler_rad": [0.0, 0.0, 0.0],
                "stationary": True,
            },
            received_monotonic_ns=200,
            stationary_since_monotonic_ns=190,
        )
