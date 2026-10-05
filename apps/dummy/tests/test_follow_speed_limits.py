import asyncio
import math
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.image_jacobian_servo import ImageJacobianServo
from dummy.robot_ws_client import RobotSnapshot
from dummy.touch_r1_adapter import TouchR1Adapter
from dummy.tracker import Target


def servo_config():
    config = load_config()
    config["image_jacobian_servo"]["divergence_px"] = 9999
    return config


def far_target():
    return Target(True, u=0, v=480, w=640, h=480, score=0.9, kind="person_lock", ts=1.0)


@pytest.mark.parametrize("dt_s", [0.05, 0.10, 0.20])
def test_j1_j4_angle_budget_scales_with_control_time(dt_s):
    servo = ImageJacobianServo(servo_config())
    measured = [0, 0, -10, 0, 0, 0]
    servo.reset(measured)
    command = servo.update(measured, far_target(), dt_s=dt_s)
    assert command.ok
    assert abs(command.delta_deg[0]) == pytest.approx(10 * dt_s)
    assert abs(command.delta_deg[3]) == pytest.approx(10 * dt_s)
    assert all(command.delta_deg[i] == 0 for i in [1, 2, 4, 5])


def test_stall_does_not_accumulate_a_large_angle_budget():
    servo = ImageJacobianServo(servo_config())
    measured = [0, 0, -10, 0, 0, 0]
    servo.reset(measured)
    command = servo.update(measured, far_target(), dt_s=20)
    assert max(abs(value) for value in command.delta_deg) <= 2.5


@pytest.mark.parametrize("current_j4,target_v,expected", [(34.8, 480, 35), (-34.8, 0, -35)])
def test_j4_absolute_limits_are_plus_minus_35(current_j4, target_v, expected):
    servo = ImageJacobianServo(servo_config())
    servo.reset([0, 0, -10, 0, 0, 0])
    measured = [0, 0, -10, current_j4, 0, 0]
    target = Target(True, u=320, v=target_v, w=640, h=480, score=0.9, kind="person_lock", ts=1)
    command = servo.update(measured, target, dt_s=0.1)
    assert command.ok
    assert command.joints_deg[3] == pytest.approx(expected)


def test_config_keeps_j1_excursion_and_replaces_fixed_angle_limits():
    config = load_config()
    robot = config["robot"]
    options = config["image_jacobian_servo"]
    axes = {axis["joint_index"]: axis for axis in options["axes"]}
    assert "max_relative_move_deg" not in robot
    assert "max_step_deg" not in options
    assert axes[0]["max_excursion_deg"] == 85
    assert axes[3]["max_excursion_deg"] == 35
    for index in (0, 3):
        assert axes[index]["max_speed_deg_s"] == 10
        assert "max_step_deg" not in axes[index]


def adapter():
    instance = TouchR1Adapter({"workspace_guard": {"enabled": False}})
    instance.client.snapshot = RobotSnapshot(
        connected=True, state_ready=True, state_name="IDLE", joints_deg=[0, 0, -10, 0, 0, 0],
    )
    instance.client.refresh_state = AsyncMock(return_value=instance.client.snapshot)
    instance.client.command_wait = AsyncMock(return_value={"type": "command_status", "status": "complete"})
    instance.client.command = AsyncMock()
    return instance


@pytest.mark.parametrize("joint", range(6))
def test_adapter_preserves_target_and_extends_short_duration_for_every_joint(joint):
    instance = adapter()
    target = list(instance.client.snapshot.joints_deg)
    target[joint] += -20 if joint == 2 else 20
    asyncio.run(instance.send_joint_target(target, time_sec=0.1, allow_large=True))
    payload = instance.client.command_wait.call_args.kwargs
    assert payload["joints_deg"] == target
    assert payload["time_sec"] == 4.0
    # Sample the standard zero-velocity-endpoint quintic used by the SDK.
    peak_speed = max(30 * u**2 * (1 - u)**2 * 20 / payload["time_sec"] for u in [i / 1000 for i in range(1001)])
    assert peak_speed <= 10.0


def test_adapter_rejects_duration_that_server_would_shorten():
    instance = adapter()
    with pytest.raises(ValueError, match="30 second"):
        asyncio.run(instance.send_joint_target([160, 0, -10, 0, 0, 0]))
    instance.client.command_wait.assert_not_awaited()


@pytest.mark.parametrize("value", [0, -1, math.nan, math.inf])
def test_adapter_rejects_invalid_speed(value):
    with pytest.raises(ValueError, match="speed"):
        TouchR1Adapter({"robot": {"max_speed_deg_s": value}, "workspace_guard": {"enabled": False}})


def test_servo_transport_carries_the_speed_limited_duration():
    instance = adapter()
    instance.follow_command = "servo"
    asyncio.run(instance.send_joint_target([20, 0, -10, 0, 0, 0], time_sec=0.1))
    args, payload = instance.client.command_wait.call_args
    assert args == ("servo",)
    assert payload["time_sec"] == 4.0


def test_zero_preset_carries_the_speed_limited_duration():
    instance = adapter()
    instance.wait_idle = AsyncMock(return_value=instance.client.snapshot)
    instance.client.open = AsyncMock()
    asyncio.run(instance.go_home())
    instance.client.command.assert_awaited_once_with("preset", name="zero", time_sec=2.0)


def test_missing_joint_feedback_refuses_speed_limited_motion():
    instance = adapter()
    instance.client.snapshot.joints_deg = []
    with pytest.raises(RuntimeError, match="fresh valid robot feedback"):
        asyncio.run(instance.send_joint_target([1, 0, -10, 0, 0, 0]))
    instance.client.command_wait.assert_not_awaited()


def test_state_refresh_failure_does_not_fall_back_to_cached_feedback():
    instance = adapter()
    instance.client.refresh_state.side_effect = TimeoutError("feedback timeout")
    with pytest.raises(TimeoutError):
        asyncio.run(instance.send_joint_target([1, 0, -10, 0, 0, 0]))
    instance.client.command_wait.assert_not_awaited()


def test_cancelled_send_keeps_completion_waiter_until_close():
    async def scenario():
        instance = adapter()
        started, finished = asyncio.Event(), asyncio.Event()
        async def complete(*_args, **_kwargs):
            started.set()
            await finished.wait()
            return {"type": "command_status", "status": "complete"}
        instance.client.command_wait = complete
        instance.client.close = AsyncMock()
        motion = asyncio.create_task(instance.send_joint_target([1, 0, -10, 0, 0, 0]))
        await started.wait()
        motion.cancel()
        with pytest.raises(asyncio.CancelledError):
            await motion
        assert not instance._inflight.done()
        closing = asyncio.create_task(instance.close())
        await asyncio.sleep(0)
        assert not closing.done()
        finished.set()
        await closing
        instance.client.close.assert_awaited_once()
        assert instance._inflight is None
    asyncio.run(scenario())
