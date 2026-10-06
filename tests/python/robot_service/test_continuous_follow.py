import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services/robot/src"))
from continuous_follow import ContinuousFollow


class Guard:
    def check(self, joints):
        return True, "test geometry"


def stream():
    s = ContinuousFollow(Guard(), speed_percent=1)
    s.begin("test", [0] * 6, 0)
    return s


def test_interpolated_samples_preserve_shared_speed_and_other_joints():
    s = stream()
    target = [math.radians(60), 0, 0, math.radians(30), 0, 0]
    previous = [0] * 6
    for step in range(1, 301):
        now = step * .01
        s.update("test", step, target, now * 1000, now, now * 1000)
        q, v, finished = s.tick(now, .01)
        assert not finished
        assert all(abs(value) <= limit + 1e-9 for value, limit in zip(v, s.speed))
        assert all(abs(a-b) <= limit * .01 + 1e-9 for a,b,limit in zip(q,previous,s.speed))
        assert all(q[i] == 0 for i in (1, 2, 4, 5))
        previous = q
    assert math.degrees(q[0]) > 20
    assert math.degrees(s.speed[0]) == pytest.approx(15)


def test_new_target_changes_direction_without_finishing_old_target():
    s = stream()
    for i in range(1, 101):
        now = i * .01
        goal = 60 if i < 40 else -60
        s.update("test", i, [math.radians(goal), 0, 0, 0, 0, 0], now*1000, now, now*1000)
        s.tick(now, .01)
    assert s.v[0] < 0


def test_watchdog_decelerates_to_hold_without_zero_or_depower():
    s = ContinuousFollow(Guard())
    s.begin("test", [math.radians(10), 0, 0, 0, 0, 0], 0)
    s.update("test", 1, [math.radians(50), 0, 0, 0, 0, 0], 0, 0, 0)
    result = None
    for i in range(1, 301):
        result = s.tick(i*.01, .01)
        if result and result[2]: break
    assert result[2] and not s.active
    assert s.reason == "observation_timeout"
    assert math.degrees(result[0][0]) > 10
    assert result[1] == [0] * 6


def test_invalid_and_replayed_observations_are_rejected():
    s = stream()
    with pytest.raises(ValueError, match="stale"):
        s.update("test", 1, [0]*6, 0, 1, 1000)
    with pytest.raises(ValueError, match="J1/J4"):
        s.update("test", 1, [0, .1, 0, 0, 0, 0], 0, 0, 0)
    with pytest.raises(ValueError, match="J4"):
        s.update("test", 1, [0, 0, 0, math.radians(36), 0, 0], 0, 0, 0)
    s.update("test", 1, [0]*6, 0, 0, 0)
    with pytest.raises(ValueError, match="increase"):
        s.update("test", 1, [0]*6, 0, 0, 0)


def test_pause_and_gesture_do_not_shift_j1_original_envelope():
    s = stream()
    s.stop()
    assert s.tick(.01, .01)[2]
    s.begin("test", [math.radians(60), 0, 0, 0, 0, 0], 1)
    with pytest.raises(ValueError, match="excursion"):
        s.update("test", 2, [math.radians(100), 0, 0, 0, 0, 0], 1000, 1, 1000)


def test_guard_rejects_intermediate_sample_without_sending_it():
    s = stream()
    s.update("test", 1, [math.radians(50), 0, 0, 0, 0, 0], 0, 0, 0)
    before = list(s.q)
    s.guard.check = lambda joints: (False, "geometry boundary")
    q, _, finished = s.tick(.01, .01)
    assert q == before and finished and s.reason == "workspace_boundary"
