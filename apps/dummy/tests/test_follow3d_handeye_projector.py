import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.follow3d.handeye_projector import FollowHandEyeProjector
from dummy.tracker import Target


ROOT = Path(__file__).resolve().parents[3]


def config():
    return {
        "follow_handeye": {
            "enabled": True,
            "calibration_path": str(
                ROOT
                / "skills/manipulation/bottlegrasp/configs/calibration/lumos-handeye.pending.json"
            ),
            "urdf_path": str(ROOT / "assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf"),
            "allow_pending_physical_validation": True,
        }
    }


def test_follow_handeye_loads_existing_thirdhand_calibration():
    projector = FollowHandEyeProjector(config())

    assert projector.available
    assert projector.calibration_id.startswith("sha256:")


def test_follow_handeye_projects_camera_xyz_with_current_fk():
    projector = FollowHandEyeProjector(config())
    target = Target(True, 320, 240, 640, 480, 0.9, "person_depth", 1.0)
    target.xyz_m = [0.0, 0.0, 1.0]

    result = projector.project([0, 0, 0, 0, 0, 0], target)

    assert result.ok
    assert result.source == "local_fk_handeye"
    assert result.xyz_m is not None
    assert len(result.xyz_m) == 3
    assert result.xyz_m != target.xyz_m


def test_follow_handeye_lifts_projected_target_above_configured_floor():
    cfg = config()
    cfg["follow_handeye"]["min_base_target_z_m"] = 0.50
    projector = FollowHandEyeProjector(cfg)
    target = Target(True, 320, 240, 640, 480, 0.9, "person_depth", 1.0)
    target.xyz_m = [0.0, 0.0, 0.2]

    result = projector.project([0, 0, 0, 0, 0, 0], target)

    assert result.ok
    assert result.xyz_m is not None
    assert result.xyz_m[2] == 0.50


def test_follow_handeye_prefers_vision_service_base_when_available():
    projector = FollowHandEyeProjector(config())
    target = Target(True, 320, 240, 640, 480, 0.9, "person_depth", 1.0)
    target.xyz_m = [0.0, 0.0, 1.0]
    target.base_xyz_m = [0.3, 0.1, 0.2]

    result = projector.project([0, 0, 0, 0, 0, 0], target)

    assert result.ok
    assert result.source == "vision_service_base"
    assert result.xyz_m == [0.3, 0.1, 0.2]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("FOLLOW3D_HANDEYE_PROJECTOR_OK")
