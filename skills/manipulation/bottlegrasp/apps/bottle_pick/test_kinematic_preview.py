"""The offline preview produces joint frames without a robot connection."""

from pathlib import Path
import unittest

from ikpy.chain import Chain

from preview_ik import solve


ROOT = Path(__file__).resolve().parents[5]
URDF = ROOT / "assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf"


class KinematicPreviewTests(unittest.TestCase):
    def test_stationary_waypoint_and_zero_return(self):
        parsed = Chain.from_urdf_file(str(URDF), base_elements=["base_link"],
                                      active_links_mask=[False] + [True] * 6 + [False])
        chain = Chain(parsed.links[:7], active_links_mask=[False] + [True] * 6)
        position = chain.forward_kinematics([0] * 7)[:3, 3].tolist()
        result = solve({"urdf": str(URDF), "startJointsDeg": [0] * 6,
                        "startFlangeM": position,
                        "stages": [{"stage": "pregrasp", "positionM": position,
                                    "eulerRad": [0, 0, 0], "gripperPosition": 1}]})
        self.assertTrue(result["complete"])
        self.assertFalse(result["robotCommandsSent"])
        self.assertFalse(result["collisionValidated"])
        self.assertEqual(result["frames"][-1]["stage"], "return_zero")
        self.assertEqual(result["frames"][-1]["jointsDeg"], [0.0] * 6)


if __name__ == "__main__":
    unittest.main()
