import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.follow3d.contracts import DumeFollowCommand
from dummy_legacy.follow3d.diagnostics import build_diagnostics
from dummy_legacy.tracker import Target
from dummy_legacy.visual_servo_gaze import VirtualGimbalCommand


def test_diagnostics_explains_virtual3d_mink_path():
    target = Target(True, 330, 250, 640, 480, 0.9, "person_lock_virtual3d", 1.0)
    command = DumeFollowCommand(True, [0, 0, 0, 0, 0, 0], VirtualGimbalCommand(True), "mink/base/virtual3d/depth_invalid_far_reach")
    rows = build_diagnostics(
        target=target,
        command=command,
        debug={
            "target_3d_mode": "virtual3d",
            "target_xyz_m": [0.1, 0.0, 1.5],
            "estimated_depth_m": 1.5,
            "estimated_depth_source": "mono_bbox",
            "estimated_depth_confidence": 0.55,
            "distance_state": "depth_invalid_far_reach",
            "distance_depth_m": 1.5,
            "distance_depth_valid": False,
        },
        error=None,
        robot_snapshot=None,
    )

    details = "\n".join(row["detail"] for row in rows)
    assert "virtual depth" in details
    assert "Mink" in details or "IK" in details


def test_diagnostics_points_to_vision_when_camera_errors():
    rows = build_diagnostics(
        target=Target(False, kind="vision_stream_unavailable"),
        command=DumeFollowCommand(False, [0, 0, 0, 0, 0, 0], VirtualGimbalCommand(False), "target_missing"),
        debug={},
        error="camera frame stale",
        robot_snapshot=None,
    )

    assert rows[0]["ok"] is False
    assert "vision" in rows[-1]["detail"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("FOLLOW3D_DIAGNOSTICS_OK")
