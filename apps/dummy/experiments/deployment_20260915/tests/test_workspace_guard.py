import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.workspace_guard import WorkspaceGuard


ROOT = Path(__file__).resolve().parents[5]
URDF = ROOT / "assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf"


def guard():
    return WorkspaceGuard(
        {
            "workspace_guard": {
                "enabled": True,
                "clearance_m": 0.0,
                "urdf_path": str(URDF),
            }
        }
    )


def test_zero_home_is_above_base_plane_guard():
    ok, reason = guard().check([0, 0, 0, 0, 0, 0])

    assert ok, reason


def test_pose_below_base_plane_is_rejected_before_robot_service():
    ok, reason = guard().check([-34.43, 51.33, -0.23, 20.0, -36.68, -51.5])

    assert not ok
    assert "below base bottom" in reason


def test_near_table_but_above_base_bottom_pose_is_allowed():
    ok, reason = guard().check([0, -12, -120, 0, 0, 0])

    assert ok, reason


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("WORKSPACE_GUARD_OK")
