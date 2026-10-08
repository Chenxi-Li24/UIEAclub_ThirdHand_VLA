import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.follow3d import DumeTouchR1FollowController
from dummy_legacy.follow3d.distance_policy import DistanceAwareCommand
from dummy_legacy.follow3d.mink_backend import MinkLookAtResult
from dummy_legacy.tracker import Target


class FakeDistance:
    def reset(self):
        self.reset_called = True

    def update(self, joints, target, estimated_depth=None):
        assert estimated_depth.depth_m == 1.2
        return DistanceAwareCommand("fake_distance", [0, 1, -1, 0, 0, 0], 1.2, False, "test", "fake", 0.5)


class FakeDepth:
    def reset(self):
        self.reset_called = True

    def estimate(self, target, debug=None):
        class Depth:
            depth_m = 1.2
            source = "fake"
            confidence = 0.5
            metric = False
            reason = "test"
        assert debug["lock_candidate"]["h"] == 100
        return Depth()


class FakeProjector:
    def ensure_xyz(self, target, *, depth_hint_m=None):
        target.xyz_m = [0.1, -0.1, 1.2]
        target.kind = "person_virtual3d"
        return True


class FakeHandEye:
    def reset(self):
        self.reset_called = True

    def project(self, joints, target):
        class Result:
            ok = True
            xyz_m = [0.4, 0.0, 0.2]
            source = "fake_handeye"
            calibration_id = "fake"
            reason = None

        target.camera_xyz_m = list(target.xyz_m)
        target.xyz_m = list(Result.xyz_m)
        return Result()


class FakeIk:
    def reset(self, joints):
        self.reset_joints = list(joints)

    def target_for(self, joints, target):
        assert target.posture_joints_deg == [0, 1, -1, 0, 0, 0]
        assert target.camera_xyz_m == [0.1, -0.1, 1.2]
        assert target.xyz_m == [0.4, 0.0, 0.2]
        return MinkLookAtResult(True, [value + 0.5 for value in joints], "fake")


class LooseIk:
    def reset(self, joints):
        self.reset_joints = list(joints)

    def target_for(self, joints, target):
        assert target.xyz_m is not None
        assert target.posture_joints_deg is not None
        return MinkLookAtResult(True, [value + 0.25 for value in joints], "loose")


def test_follow3d_controller_accepts_injected_modules():
    controller = DumeTouchR1FollowController(
        {},
        distance_policy=FakeDistance(),
        depth_estimator=FakeDepth(),
        target_projector=FakeProjector(),
        handeye_projector=FakeHandEye(),
        ik_backend=FakeIk(),
    )
    joints = [0, 0, 0, 0, 0, 0]
    controller.reset(joints)
    target = Target(True, 320, 240, 640, 480, 0.9, "person", 1.0)

    command = controller.target_for(joints, target, debug={"lock_candidate": {"h": 100}})

    assert command.target_found
    assert command.source == "mink/base/virtual3d/fake_distance"
    assert command.joints_deg == [0.5] * 6
    assert command.debug["target_3d_mode"] == "virtual3d"
    assert command.debug["estimated_depth_source"] == "fake"
    assert command.debug["handeye_source"] == "fake_handeye"


def test_follow3d_controller_keeps_following_with_mono_depth_only():
    controller = DumeTouchR1FollowController(
        {
            "monocular_depth": {
                "focal_px": 500.0,
                "assumed_body_height_m": 1.6,
                "smoothing_alpha": 1.0,
            },
            "virtual_3d_target": {"enabled": True, "focal_px": 500.0, "smoothing_alpha": 1.0},
        },
        handeye_projector=FakeHandEye(),
        ik_backend=LooseIk(),
    )
    joints = [0, 0, 0, 0, 0, 0]
    controller.reset(joints)
    target = Target(True, 380, 240, 640, 480, 0.9, "person_lock", 1.0)

    command = controller.target_for(joints, target, debug={"lock_candidate": {"u": 380, "v": 240, "w": 80, "h": 320, "kind": "person"}})

    assert command.target_found
    assert command.source.startswith("mink/base/virtual3d/")
    assert command.debug["estimated_depth_source"] == "mono_bbox"
    assert command.debug["target_3d_mode"] == "virtual3d"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("FOLLOW3D_MODULARITY_OK")
