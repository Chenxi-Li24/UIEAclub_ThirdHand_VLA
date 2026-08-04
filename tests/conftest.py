"""Shared test fixtures and mocks."""

from unittest.mock import MagicMock

import pytest

from uiea_thirdhand_vla.utils.types import JointState, Pose


@pytest.fixture
def mock_robot():
    robot = MagicMock()
    robot.get_joint_angles.return_value = (0.0, -30.0, -60.0, -90.0, 0.0, 0.0)
    robot.get_ee_pose.return_value = (0.3, 0.0, 0.15, 0.0, 0.0, 0.0)
    return robot


@pytest.fixture
def mock_camera():
    import numpy as np
    cam = MagicMock()
    cam.capture.return_value = np.zeros((720, 1280, 3), dtype=np.uint8)
    cam.is_open = True
    return cam


@pytest.fixture
def sample_pose():
    return Pose(position=(0.3, 0.0, 0.15), orientation=(0.0, 0.0, 0.0))


@pytest.fixture
def sample_joint_state():
    return JointState(
        positions=(0.0, -30.0, -60.0, -90.0, 0.0, 0.0),
        velocities=(0.0,) * 6
    )
