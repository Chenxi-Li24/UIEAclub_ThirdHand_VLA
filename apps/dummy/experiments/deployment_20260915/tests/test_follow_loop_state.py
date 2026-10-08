import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.follow_loop_state import clamp_to_workspace_guard, should_advance_local_joints


def test_dry_run_advances_after_guard_accepts_target():
    assert should_advance_local_joints(enable_motion=False, guard_ok=True, sent=False)


def test_guard_reject_never_advances_local_joints():
    assert not should_advance_local_joints(enable_motion=False, guard_ok=False, sent=False)
    assert not should_advance_local_joints(enable_motion=True, guard_ok=False, sent=True)


def test_hardware_busy_without_send_does_not_advance_local_joints():
    assert not should_advance_local_joints(enable_motion=True, guard_ok=True, sent=False)


def test_hardware_sent_advances_local_joints():
    assert should_advance_local_joints(enable_motion=True, guard_ok=True, sent=True)


class ThresholdGuard:
    def check(self, joints):
        value = float(joints[0])
        if value <= 10.0:
            return True, f"safe {value:.2f}"
        return False, f"unsafe {value:.2f}"


def test_workspace_clamp_returns_last_safe_interpolation():
    command, exact, reason = clamp_to_workspace_guard([0, 0, 0, 0, 0, 0], [20, 0, 0, 0, 0, 0], ThresholdGuard())

    assert not exact
    assert 9.9 <= command[0] <= 10.0
    assert reason.startswith("clamped_workspace")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("FOLLOW_LOOP_STATE_OK")
