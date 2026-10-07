import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.gateway_1023 import Gateway1023Policy


def policy():
    return Gateway1023Policy(max_delta_deg=0.75, min_interval_s=0.2)


def test_gateway_default_trusts_robot_service_motion_policy_for_move_joint():
    result = Gateway1023Policy().validate(
        {"cmd": "move_joint", "joints_deg": [20.0, 0, -20, 20, 10, 0]},
        [0, 0, -4, 0, 0, 0],
        now=1.0,
    )

    assert result.ok
    assert result.message["joints_deg"] == [20.0, 0.0, -20.0, 20.0, 10.0, 0.0]


def test_gateway_allows_small_move_joint_commands():
    result = policy().validate(
        {"cmd": "move_joint", "joints_deg": [0.2, 0, -4, 33.3, 0, 0]},
        [0, 0, -4, 33, 0, 0],
        now=1.0,
    )

    assert result.ok
    assert result.message["cmd"] == "move_joint"
    assert result.message["source"] == "dummy_1023_gateway"


def test_gateway_allows_small_filtered_servo_commands():
    result = policy().validate(
        {"cmd": "servo", "joints": [0.2, 0, -4, 33.3, 0, 0]},
        [0, 0, -4, 33, 0, 0],
        now=1.0,
    )

    assert result.ok
    assert result.message["cmd"] == "servo"
    assert result.message["joints"] == [0.2, 0.0, -4.0, 33.3, 0.0, 0.0]


def test_gateway_allows_non_motion_service_commands():
    gateway = policy()

    for command in ("connect", "disconnect", "status", "get_state", "ping", "software_stop"):
        result = gateway.validate({"cmd": command, "request_id": f"req-{command}"}, [], now=1.0)
        assert result.ok
        assert result.message == {"cmd": command, "request_id": f"req-{command}"}


def test_gateway_allows_only_home_and_zero_presets():
    gateway = policy()

    for name in ("home", "zero"):
        result = gateway.validate({"cmd": "preset", "name": name, "request_id": f"req-{name}"}, [], now=1.0)
        assert result.ok
        assert result.message == {"cmd": "preset", "name": name, "request_id": f"req-{name}"}

    blocked = gateway.validate({"cmd": "preset", "name": "unsafe"}, [], now=1.0)
    assert not blocked.ok
    assert blocked.code == "command_blocked"


def test_gateway_rejects_force_raw_and_unsafe_motion_commands():
    gateway = policy()

    for command in ("force", "set_joint_raw", "move_l"):
        result = gateway.validate({"cmd": command}, [0, 0, -4, 33, 0, 0], now=1.0)
        assert not result.ok
        assert result.code == "command_blocked"


def test_gateway_rejects_large_relative_joint_steps():
    result = policy().validate(
        {"cmd": "move_joint", "joints_deg": [2.0, 0, -4, 33, 0, 0]},
        [0, 0, -4, 33, 0, 0],
        now=1.0,
    )

    assert not result.ok
    assert result.code == "relative_step_limit"


def test_gateway_clamps_large_servo_steps_instead_of_stalling_follow():
    result = policy().validate(
        {"cmd": "servo", "joints": [10.0, 0, -4, 33, 0, 0]},
        [0, 0, -4, 33, 0, 0],
        now=1.0,
    )

    assert result.ok
    assert result.message["joints"][0] == 0.75


def test_gateway_rate_limits_motion_commands():
    gateway = policy()
    first = gateway.validate(
        {"cmd": "move_joint", "joints_deg": [0.2, 0, -4, 33, 0, 0]},
        [0, 0, -4, 33, 0, 0],
        now=1.0,
    )
    second = gateway.validate(
        {"cmd": "move_joint", "joints_deg": [0.3, 0, -4, 33, 0, 0]},
        [0.2, 0, -4, 33, 0, 0],
        now=1.05,
    )

    assert first.ok
    assert not second.ok
    assert second.code == "rate_limited"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("GATEWAY_1023_OK")
