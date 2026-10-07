import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.head_body_controller import HeadBodyLookController
from dummy.tracker import Target


def make_controller():
    cfg = load_config()
    cfg["head_body_follow"] = {
        "head_yaw_joint_index": 3,
        "head_pitch_joint_index": 4,
        "roll_joint_index": 5,
        "body_joint_indices": [0, 1, 2],
        "deadzone_px": 12,
        "k_head_yaw_deg_per_px": -0.02,
        "k_head_pitch_deg_per_px": -0.018,
        "k_body_yaw_deg_per_px": -0.003,
        "max_head_step_deg": 1.5,
        "max_body_step_deg": 0.25,
        "max_roll_step_deg": 0.2,
        "head_comfort_deg": 8.0,
        "head_recentering_gain": 0.3,
        "roll_neutral_deg": 0.0,
    }
    return HeadBodyLookController(cfg)


def target(u, v=240, *, kind="face"):
    return Target(True, u, v, 640, 480, 0.9, kind, 1.0)


def test_small_image_error_moves_head_joints_before_body_joints():
    controller = make_controller()
    joints = [0, 0, -4, 33, 0, 5]

    command = controller.target_for(joints, target(500, 170))

    assert command[0:3] == joints[0:3]
    assert command[3] != joints[3]
    assert command[4] != joints[4]
    assert abs(command[5]) < abs(joints[5])


def test_body_follows_when_head_yaw_is_outside_comfort_zone():
    controller = make_controller()
    joints = [0, 0, -4, 45, 0, 0]
    controller.reset_base([0, 0, -4, 33, 0, 0])

    command = controller.target_for(joints, target(500, 240))

    assert command[0] != joints[0]
    assert abs(command[3] - 33) < abs(joints[3] - 33)
    assert command[1] == joints[1]
    assert command[2] == joints[2]


def test_missing_target_holds_but_short_hold_target_keeps_tracking():
    controller = make_controller()
    joints = [2, 0, -4, 40, 3, 1]
    controller.reset_base([0, 0, -4, 33, 0, 0])

    missing = controller.target_for(joints, Target(False, w=640, h=480, ts=1.0))
    held = controller.target_for(joints, target(40, 100, kind="face_hold"))

    assert missing == joints
    assert held != joints


def test_output_is_clamped_to_joint_limits_and_step_limits():
    controller = make_controller()
    joints = [161.9, 200.9, -0.1, 97.8, 97.8, 163.9]
    controller.reset_base([160, 200, -1, 97, 97, 163])

    command = controller.target_for(joints, target(0, 0))
    limits = load_config()["robot"]["joint_limits_deg"]

    assert all(lo <= value <= hi for value, (lo, hi) in zip(command, limits))
    assert abs(command[3] - joints[3]) <= 1.5
    assert abs(command[4] - joints[4]) <= 1.5
    assert abs(command[5] - joints[5]) <= 0.2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("HEAD_BODY_CONTROLLER_OK")
