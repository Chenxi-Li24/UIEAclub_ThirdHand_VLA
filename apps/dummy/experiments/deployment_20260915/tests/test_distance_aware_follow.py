import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.distance_aware_follow import DistanceAwarePosturePolicy
from dummy_legacy.tracker import Target


def config():
    return {
        "robot": {
            "home_joints_deg": [0, 0, 0, 0, 0, 0],
            "joint_limits_deg": [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
        },
        "distance_follow": {
            "enabled": True,
            "desired_depth_m": 0.30,
            "deadband_m": 0.05,
            "too_close_m": 0.30,
            "far_depth_m": 1.15,
            "posture_step_deg": 0.5,
            "active_joint_indices": [1, 2, 4],
            "far_reach_pose_deg": [0, 8, -10, 0, 0, 0],
            "hold_pose_deg": [0, 0, 0, 0, 0, 0],
            "retract_pose_deg": [0, -2, -4, -6, 0, 0],
        },
    }


def target(depth=None, valid=False):
    t = Target(True, 320, 240, 640, 480, 0.9, "person_lock", 1.0)
    t.depth_m = depth
    t.depth_valid = valid
    if depth is not None:
        t.xyz_m = [0.0, 0.0, depth]
    return t


def test_depth_invalid_reaches_forward_slowly():
    policy = DistanceAwarePosturePolicy(config())

    command = policy.update([0, 0, 0, 0, 0, 0], target())

    assert command.state == "depth_invalid_far_reach"
    assert command.posture_joints_deg[1] == 0.5
    assert command.posture_joints_deg[2] == -0.5


def test_too_close_retracts_body_axes():
    policy = DistanceAwarePosturePolicy(config())

    command = policy.update([0, 0, 0, 0, 0, 0], target(0.25, True))

    assert command.state == "too_close_retract"
    assert command.posture_joints_deg[1] == -0.5
    assert command.posture_joints_deg[2] == -0.5


def test_apply_bias_only_changes_configured_body_axes():
    policy = DistanceAwarePosturePolicy(config())
    command = policy.update([1, 0, 0, 2, 0, 3], target(1.4, True))

    out = policy.apply_bias([1, 10, -10, 2, 5, 3], command)

    assert out[0] == 1
    assert out[3] == 2
    assert out[5] == 3
    assert out[1] == command.posture_joints_deg[1]
    assert out[2] == command.posture_joints_deg[2]
    assert out[4] == command.posture_joints_deg[4]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("DISTANCE_AWARE_FOLLOW_OK")
