import sys
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.dume_touch_r1_follow import DumeTouchR1FollowController
from dummy.mink_lookat_controller import MinkLookAtResult
from dummy.mink_lookat_controller import MinkLookAtController
from dummy.tracker import Target
from dummy.touch_r1_gimbal_mapper import TouchR1GimbalMapper, VirtualGimbalState
from dummy.visual_servo_gaze import VisualServoGazeController
from dummy.image_jacobian_servo import ImageJacobianServo


def target(u, v, *, w=640, h=480, found=True, kind="person_lock"):
    return Target(found, u=u, v=v, w=w, h=h, score=0.9, kind=kind, ts=1.0)


def config():
    return {
        "robot": {
            "joint_limits_deg": [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
        },
        "visual_servo_gaze": {
            "deadzone_px": 10,
            "pan_kp_deg_per_px": -0.02,
            "tilt_kp_deg_per_px": 0.02,
            "max_pan_step_deg": 1.0,
            "max_tilt_step_deg": 1.0,
            "lost_hold_frames": 3,
        },
        "touch_r1_gimbal": {
            "pan_joint_index": 0,
            "tilt_joint_index": 3,
            "roll_joint_index": 5,
            "body_yaw_joint_index": 0,
            "pan_sign": 1,
            "tilt_sign": 1,
            "roll_sign": 1,
            "body_yaw_sign": 1,
            "pan_comfort_deg": 999.0,
            "body_follow_gain": 0.0,
            "max_body_step_deg": 0.0,
            "roll_neutral_deg": 0.0,
            "max_roll_step_deg": 0.2,
        },
        "image_jacobian_servo": {
            "enabled": True,
            "deadzone_px": 10,
            "gain": 0.5,
            "max_speed_deg_s": 10.0,
            "control_period_s": 0.2,
            "max_excursion_deg": 40.0,
            "axes": [
                {"name": "J1_yaw", "joint_index": 0, "px_per_deg": [5.0, 0.0], "max_speed_deg_s": 10.0, "max_excursion_deg": 10.0},
                {"name": "J2_disabled", "joint_index": 1, "px_per_deg": [100.0, 0.0], "enabled": False},
                {"name": "J4_pitch", "joint_index": 3, "px_per_deg": [0.0, -4.0], "max_speed_deg_s": 10.0, "max_excursion_deg": 10.0},
            ],
        },
        "distance_follow": {
            "enabled": True,
            "posture_step_deg": 0.5,
            "active_joint_indices": [1, 2, 4],
            "far_reach_pose_deg": [0, 8, -10, 0, 0, 0],
            "hold_pose_deg": [0, 0, 0, 0, 0, 0],
            "retract_pose_deg": [0, -2, -4, -6, 0, 0],
        },
        "virtual_3d_target": {
            "enabled": True,
            "default_depth_m": 1.5,
            "focal_px": 500.0,
            "max_x_m": 0.8,
            "max_y_m": 0.5,
        },
    }


def test_visual_servo_outputs_virtual_gimbal_steps_and_short_hold():
    servo = VisualServoGazeController(config())

    command = servo.update(target(220, 190))
    assert command.found
    assert command.pan_delta_deg > 0.0
    assert command.tilt_delta_deg < 0.0

    held = servo.update(target(0, 0, found=False, kind="person_lock_lost"))
    assert held.found
    assert held.hold
    assert held.pan_delta_deg == command.pan_delta_deg


def test_visual_servo_stops_axis_when_same_direction_correction_worsens_error():
    servo = VisualServoGazeController(config())

    first = servo.update(target(240, 240))
    second = servo.update(target(210, 240))

    assert first.pan_delta_deg > 0.0
    assert second.pan_delta_deg == 0.0


def test_visual_servo_can_disable_tilt_for_uncommissioned_hardware_axis():
    cfg = config()
    cfg["visual_servo_gaze"]["tilt_enabled"] = False
    servo = VisualServoGazeController(cfg)

    command = servo.update(target(320, 120))

    assert command.found
    assert command.pan_delta_deg == 0.0
    assert command.tilt_delta_deg == 0.0


def test_touch_r1_mapper_moves_head_first_then_recenters_with_body_follow():
    mapper = TouchR1GimbalMapper(config())
    mapper.reset([0, 0, 0, 0, 0, 0])

    first = mapper.apply([0, 0, 0, 0, 0, 0], VirtualGimbalState(pan_delta_deg=1.0, tilt_delta_deg=0.5))
    assert first[0] == 1.0
    assert first[3] == 0.5

    body_follow = mapper.apply([4.0, 0, 0, 0, 0, 0], VirtualGimbalState(pan_delta_deg=1.0, tilt_delta_deg=0.0))
    assert body_follow[0] == 5.0


def test_dume_touch_r1_follow_controller_turns_target_into_joint_command():
    class FakeMink:
        def reset(self, joints):
            pass

        def target_for(self, joints, target):
            assert target.xyz_m is not None
            assert target.depth_valid is False
            return MinkLookAtResult(True, [value + 1.0 for value in joints], "fake_mink")

    controller = DumeTouchR1FollowController(config(), mink_controller=FakeMink())
    joints = [0, 0, 0, 0, 0, 0]
    controller.reset(joints)

    command = controller.target_for(joints, target(200, 180))

    assert command.target_found
    assert command.source.startswith(("mink/base/virtual3d/", "mink/camera/virtual3d/"))
    assert command.debug["estimated_depth_source"] == "fallback"
    assert command.joints_deg == [1.0] * 6


def test_image_jacobian_servo_solves_joint_steps_from_pixel_error():
    servo = ImageJacobianServo(config())
    servo.reset([0, 0, 0, 0, 0, 0])

    command = servo.update([0, 0, 0, 0, 0, 0], target(220, 300))

    assert command.ok
    assert command.joints_deg[0] > 0.0
    assert command.joints_deg[3] > 0.0
    assert command.joints_deg[1] == 0.0
    assert command.error_px == (-100.0, 60.0)
    assert command.delta_deg is not None


def test_image_jacobian_servo_clamps_to_base_excursion_and_joint_limits():
    cfg = config()
    cfg["image_jacobian_servo"]["axes"][0]["max_excursion_deg"] = 1.0
    cfg["robot"]["joint_limits_deg"][0] = [-0.5, 0.75]
    servo = ImageJacobianServo(cfg)
    servo.reset([0, 0, 0, 0, 0, 0])

    command = servo.update([0, 0, 0, 0, 0, 0], target(0, 240))

    assert command.ok
    assert command.joints_deg[0] == 0.75


def test_image_jacobian_servo_respects_axis_absolute_limits():
    cfg = config()
    cfg["image_jacobian_servo"]["axes"] = [
        {
            "name": "J4_tilt_micro",
            "joint_index": 3,
            "px_per_deg": [0.0, -4.0],
            "max_speed_deg_s": 10.0,
            "min_deg": -2.0,
            "max_deg": 8.0,
        },
    ]
    servo = ImageJacobianServo(cfg)
    servo.reset([0, 0, 0, 7.9, 0, 0])

    command = servo.update([0, 0, 0, 7.9, 0, 0], target(320, 480))

    assert command.ok
    assert command.joints_deg[3] <= 8.0


def test_image_jacobian_servo_holds_when_current_pose_is_outside_follow_range():
    cfg = config()
    cfg["image_jacobian_servo"]["deadzone_px"] = 999
    cfg["image_jacobian_servo"]["axes"] = [
        {
            "name": "J4_tilt_micro",
            "joint_index": 3,
            "px_per_deg": [0.0, -4.0],
            "max_speed_deg_s": 10.0,
            "min_deg": -1.5,
            "max_deg": 4.0,
        },
    ]
    servo = ImageJacobianServo(cfg)
    servo.reset([0, 0, 0, 8.6, 0, 0])

    command = servo.update([0, 0, 0, 8.6, 0, 0], target(320, 240))

    assert not command.ok
    assert command.reason == "outside_follow_range"
    assert command.joints_deg[3] == 8.6


def test_image_jacobian_servo_loads_axis_response_calibration_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "axis-response.json"
        path.write_text(
            """
{
  "summary": {
    "J1": {"avg_px_per_deg": [8.0, 0.0]},
    "J4": {"avg_px_per_deg": [0.0, -8.0]}
  }
}
""",
            encoding="utf-8",
        )
        cfg = config()
        cfg["image_jacobian_servo"]["calibration_path"] = str(path)
        servo = ImageJacobianServo(cfg)
        servo.reset([0, 0, 0, 0, 0, 0])

        command = servo.update([0, 0, 0, 0, 0, 0], target(220, 300))

    assert command.ok
    assert 0.0 < command.joints_deg[0] <= 2.0
    assert 0.0 < command.joints_deg[3] <= 2.0


def test_dume_touch_r1_follow_controller_uses_mink_when_3d_target_is_available():
    class FakeMink:
        available = True
        unavailable_reason = None

        def reset(self, joints):
            self.base = list(joints)

        def target_for(self, joints, target):
            return MinkLookAtResult(True, [value + 1.0 for value in joints], "fake_mink")

    controller = DumeTouchR1FollowController(config(), mink_controller=FakeMink())
    joints = [0, 0, 0, 0, 0, 0]
    controller.reset(joints)
    t = target(320, 240)
    t.xyz_m = [0.4, 0.0, 0.85]
    t.depth_m = 0.85
    t.depth_valid = True

    command = controller.target_for(joints, t)

    assert command.source in {
        "mink/base/depth3d/hold_distance",
        "mink/camera/depth3d/hold_distance",
    }
    assert command.joints_deg == [1.0] * 6


def test_dume_touch_r1_follow_controller_stops_when_mink_is_unavailable():
    class FakeMink:
        def reset(self, joints):
            pass

        def target_for(self, joints, target):
            return MinkLookAtResult(False, list(joints), "unavailable")

    controller = DumeTouchR1FollowController(config(), mink_controller=FakeMink())
    joints = [0, 0, 0, 0, 0, 0]
    controller.reset(joints)

    command = controller.target_for(joints, target(200, 180))

    assert not command.target_found
    assert command.joints_deg == joints
    assert command.source == "mink_failed/unavailable"


def test_mink_controller_resolves_startouch_package_uri_when_enabled():
    cfg = config()
    cfg["mink_lookat"] = {
        "enabled": True,
        "model_path": "assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf",
    }

    controller = MinkLookAtController(cfg)

    assert controller.available
    assert controller.unavailable_reason is None


def test_mink_controller_solves_3d_lookat_to_six_joint_target():
    cfg = config()
    cfg["mink_lookat"] = {
        "enabled": True,
        "model_path": "assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf",
        "camera_frame": "gripper_base",
        "frame_type": "body",
        "dt": 0.1,
        "solver": "daqp",
    }
    controller = MinkLookAtController(cfg)
    t = target(320, 240)
    t.xyz_m = [0.35, 0.05, 0.2]

    result = controller.target_for([0, 0, 0, 0, 0, 0], t)

    assert result.ok
    assert len(result.joints_deg) == 6


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("DUME_TOUCH_R1_FOLLOW_CONTROL_OK")
