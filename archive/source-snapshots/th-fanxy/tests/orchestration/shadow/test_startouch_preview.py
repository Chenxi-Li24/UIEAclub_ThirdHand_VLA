import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from uiea_thirdhand_vla.orchestration.shadow.startouch_preview import (
    GripperPreview,
    JointWaypointPreview,
    LinearPosePreview,
    StartouchCommandPreview,
    load_shadow_limits,
)

ROOT = Path(__file__).resolve().parents[3]
LIMITS_PATH = ROOT / "configs" / "orchestration" / "startouch_shadow.yaml"


def envelope(command):
    return StartouchCommandPreview(
        request_id="episode-1:pick-1:0",
        episode_id="episode-1",
        step_id="pick-1",
        attempt=0,
        policy_id="shadow.pick",
        policy_version="0.1.0",
        contract_version="0.1.0",
        command=command,
    )


def joint_preview(**changes):
    payload = {
        "command_type": "move_joint_path",
        "waypoints_rad": ((0.0, -0.1, -0.2, 0.0, 0.0, 0.0),),
        "time_sec": 2.0,
        "speed_percent": 20.0,
        "angle_unit": "rad",
    }
    payload.update(changes)
    return JointWaypointPreview.model_validate(payload)


def linear_preview(**changes):
    payload = {
        "command_type": "move_l",
        "position_m": (0.35, 0.0, 0.2),
        "euler_rad": (0.0, math.pi, 0.0),
        "frame": "robot_base",
        "calibration_id": "handeye-current",
        "time_sec": 2.0,
        "position_tolerance_m": 0.008,
        "orientation_tolerance_rad": 0.12,
        "position_unit": "m",
        "orientation_unit": "rad",
    }
    payload.update(changes)
    return LinearPosePreview.model_validate(payload)


def test_joint_preview_requires_six_finite_radians_and_checked_limits():
    limits = load_shadow_limits(LIMITS_PATH)

    limits.validate_preview(envelope(joint_preview()))

    with pytest.raises(ValidationError):
        joint_preview(waypoints_rad=((0.0,) * 5,))
    with pytest.raises(ValidationError, match="finite"):
        joint_preview(waypoints_rad=((0.0, 0.0, math.inf, 0.0, 0.0, 0.0),))
    with pytest.raises(ValueError, match="joint 2"):
        limits.validate_preview(
            envelope(
                joint_preview(waypoints_rad=((0.0, -1.0, -0.2, 0.0, 0.0, 0.0),))
            )
        )


def test_linear_preview_requires_explicit_frame_calibration_units_and_bounds():
    limits = load_shadow_limits(LIMITS_PATH)

    limits.validate_preview(envelope(linear_preview()))

    with pytest.raises(ValidationError):
        linear_preview(frame="")
    with pytest.raises(ValidationError):
        linear_preview(calibration_id="")
    with pytest.raises(ValidationError):
        linear_preview(position_unit="mm")
    with pytest.raises(ValueError, match="frame"):
        limits.validate_preview(envelope(linear_preview(frame="camera")))
    with pytest.raises(ValueError, match="duration"):
        limits.validate_preview(envelope(linear_preview(time_sec=31.0)))


def test_gripper_units_are_mutually_exclusive_and_bounded():
    limits = load_shadow_limits(LIMITS_PATH)
    normalized = GripperPreview(
        command_type="gripper",
        position_normalized=0.5,
        position_unit="normalized",
    )

    limits.validate_preview(envelope(normalized))

    with pytest.raises(ValidationError, match="exactly one"):
        GripperPreview(command_type="gripper", position_unit="normalized")
    with pytest.raises(ValidationError, match="exactly one"):
        GripperPreview(
            command_type="gripper",
            position_normalized=0.5,
            distance_m=0.02,
            position_unit="normalized",
        )
    with pytest.raises(ValidationError):
        GripperPreview(
            command_type="gripper",
            distance_m=0.02,
            position_unit="normalized",
        )


def test_envelope_is_frozen_strict_and_execution_is_literal_false():
    preview = envelope(joint_preview())

    assert preview.robot_execution_enabled is False
    assert preview.can_execute_world is False
    with pytest.raises(ValidationError):
        StartouchCommandPreview.model_validate(
            {**preview.model_dump(mode="json"), "robot_execution_enabled": True}
        )
    with pytest.raises(ValidationError):
        StartouchCommandPreview.model_validate(
            {**preview.model_dump(mode="json"), "unexpected": True}
        )
    with pytest.raises(ValidationError):
        preview.step_id = "changed"


def test_limits_have_pinned_provenance_and_strict_shape():
    limits = load_shadow_limits(LIMITS_PATH)

    assert limits.source_path == "web-control/server/startouch_bridge.py"
    assert len(limits.source_commit) == 40
    assert limits.robot_execution_enabled is False
