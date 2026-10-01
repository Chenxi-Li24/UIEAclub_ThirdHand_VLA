"""Numerical and freshness checks for read-only base projection."""

import math
from pathlib import Path
import time
import unittest

import numpy as np

from handeye_projection import HandEyeProjection, flange_transform, project_point


ROOT = Path(__file__).resolve().parents[3]
CALIBRATION = ROOT / "skills/manipulation/bottlegrasp/configs/calibration/lumos-handeye.pending.json"
URDF = ROOT / "assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf"


class HandEyeProjectionTests(unittest.TestCase):
    def setUp(self):
        self.projection = HandEyeProjection(
            CALIBRATION, "250801DR48FP25002738",
            "xvisio-sdk:250801DR48FP25002738",
            "luming_eih_20260817_250801DR48FP25002738_85a58f8a28ac", URDF,
        )

    def test_rpy_and_homogeneous_point(self):
        transform = flange_transform([1, 2, 3], [0, 0, math.pi / 2])
        self.assertTrue(np.allclose(project_point(transform, [1, 0, 1]), [1, 3, 4]))

    def test_matching_stationary_zero_state_is_accepted(self):
        now = time.monotonic_ns()
        state = {"type": "arm_state", "pose_frame": "robot_flange",
                 "connected": True, "healthy": True, "stationary": True,
                 "flange_position_m": [0.1275, 0, 0.17605],
                 "flange_euler_rad": [0, 0, 0], "joints_deg": [0] * 6,
                 "observed_monotonic_ns": now}
        self.assertTrue(self.projection.update(state, now))
        self.assertIsNotNone(self.projection.for_frame(now))
        self.assertEqual(self.projection.joints_for_frame(now), [0] * 6)
        self.assertIsNone(self.projection.for_frame(now + 251_000_000))
        state["flange_position_m"] = [0.26, 0, 0.065]
        self.assertFalse(self.projection.update(state, now))
        self.assertEqual(self.projection.last_rejection, "robot_urdf_fk_mismatch")
        self.assertIsNone(self.projection.for_frame(now))


if __name__ == "__main__":
    unittest.main()
