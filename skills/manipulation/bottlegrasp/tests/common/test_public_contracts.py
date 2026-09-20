import json
from importlib.resources import files
import unittest


class PublicContractTests(unittest.TestCase):
    def test_readme_python_reuse_imports_are_public(self):
        from thirdhand_va.action.calibration import HandEyeCalibration
        from thirdhand_va.vision import VisionPipeline
        from thirdhand_va.vision.camera import read_frame_bundle
        from thirdhand_va.vision.geometry import estimate_grasp_pose
        from thirdhand_va.vision.selection import SpatialBottleSelector

        for exported in (
            HandEyeCalibration,
            VisionPipeline,
            read_frame_bundle,
            estimate_grasp_pose,
            SpatialBottleSelector,
        ):
            self.assertTrue(callable(exported))

    def test_common_exports_canonical_contract_names(self):
        from thirdhand_va.common import ArmState, RgbdFrame, VisionConfig, VisionResult
        from thirdhand_va.common.contracts import (
            ArmState as ContractArmState,
            RgbdFrame as ContractRgbdFrame,
            TrackedBottle,
            VisionDecision,
            VisionResult as ContractVisionResult,
        )

        self.assertIs(ArmState, ContractArmState)
        self.assertIs(RgbdFrame, ContractRgbdFrame)
        self.assertIs(VisionResult, ContractVisionResult)
        self.assertIs(VisionResult, VisionDecision)
        self.assertEqual(VisionConfig.__name__, "VisionConfig")
        self.assertEqual(TrackedBottle.__name__, "TrackedBottle")

    def test_cross_language_schema_is_fail_closed(self):
        schema_text = (
            files("thirdhand_va.common.contracts")
            .joinpath("vision-result.schema.json")
            .read_text(encoding="utf-8")
        )
        schema = json.loads(schema_text)

        self.assertEqual(schema["properties"]["robot_control_enabled"], {"const": False})
        self.assertEqual(
            schema["properties"]["status"]["enum"],
            ["searching", "rejected", "uncertain", "unstable", "ready"],
        )
        self.assertTrue(
            {
                "schema",
                "robot_control_enabled",
                "status",
                "frame_id",
                "reasons",
                "stable_hits",
                "window_size",
            }.issubset(schema["required"])
        )
        self.assertEqual(schema["properties"]["schema"], {"const": "thirdhand-va-decision-v3"})
        self.assertTrue(
            {
                "request_id",
                "selected_stable_id",
                "tracks",
                "captured_monotonic_ns",
                "camera_serial",
                "registration_id",
                "motion_epoch",
                "evidence_id",
            }.issubset(schema["required"])
        )


if __name__ == "__main__":
    unittest.main()
