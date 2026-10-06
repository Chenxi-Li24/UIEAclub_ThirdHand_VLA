import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.workspace_guard import WorkspaceGuard, _LinkMesh


ROOT = Path(__file__).resolve().parents[3]
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


def test_z_reduction_matches_full_rigid_transform():
    rng = np.random.default_rng(42)
    points = rng.normal(size=(1000, 3))
    rotation, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = [.1, -.2, .3]
    instance = WorkspaceGuard({"workspace_guard": {"enabled": False}})
    instance._links = {"link1": _LinkMesh(points)}
    instance._link_transforms = lambda _joints: {"link1": transform}
    expected = np.min((points @ rotation.T + transform[:3, 3])[:, 2])
    assert instance.min_geometry_z_m([0] * 6) == pytest.approx(expected, abs=1e-12)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("WORKSPACE_GUARD_OK")
