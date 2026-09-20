from pathlib import Path
import unittest


class RepositoryLayoutTests(unittest.TestCase):
    def test_no_backup_or_duplicate_python_sources_remain(self) -> None:
        root = Path(".")
        self.assertEqual([], list(root.rglob("*.py..bak")))
        self.assertFalse(Path("src/thirdhand_va/grounded_sam.py").exists())

    def test_approved_target_files_exist(self) -> None:
        required = {
            "configs/action.yaml",
            "src/thirdhand_va/common/errors.py",
            "src/thirdhand_va/common/contracts/arm_state.py",
            "src/thirdhand_va/action/observation/depth_filter.js",
            "src/thirdhand_va/action/observation/target_memory.js",
            "src/thirdhand_va/action/observation/base_target_lock.js",
            "src/thirdhand_va/action/alignment/visual_align_controller.js",
            "src/thirdhand_va/action/grasp/grasp_controller.js",
            "src/thirdhand_va/action/grasp/workflow.js",
            "src/thirdhand_va/action/safety/execution_gate.js",
            "src/thirdhand_va/action/safety/workspace_check.js",
            "src/thirdhand_va/action/safety/software_stop.js",
            "src/thirdhand_va/action/adapters/vision_client.js",
            "src/thirdhand_va/action/adapters/robot_client.js",
            "src/thirdhand_va/action/adapters/robot_ws_client.js",
            "src/thirdhand_va/action/operator/status_store.js",
            "src/thirdhand_va/action/operator/controller.js",
            "apps/bottle_pick/camera_bridge.py",
            "apps/bottle_pick/web_server.js",
            "apps/bottle_pick/run.js",
            "scripts/vision/camera_smoke.py",
            "scripts/vision/record_rgbd.py",
            "scripts/vision/replay_rgbd.py",
            "scripts/vision/debug_perception.py",
            "scripts/vision/debug_selection.py",
            "scripts/vision/debug_geometry.py",
            "scripts/vision/debug_pipeline.py",
            "scripts/action/debug_calibration.py",
            "scripts/action/debug_alignment.js",
            "scripts/action/debug_grasp.js",
            "scripts/action/debug_workflow.js",
            "scripts/action/operator_control.sh",
            "docs/vision/modules.md",
            "docs/action/modules.md",
            "docs/integration/contracts.md",
        }
        missing = sorted(path for path in required if not Path(path).is_file())
        self.assertEqual([], missing)

    def test_project_declares_reproducible_python_and_node_runtimes(self) -> None:
        required = {
            "requirements/vision-cu128.txt",
            "package.json",
            "package-lock.json",
            "docs/dependencies.md",
            "scripts/runtime/preflight.py",
        }

        missing = sorted(path for path in required if not Path(path).is_file())

        self.assertEqual([], missing)

    def test_migration_only_paths_are_removed(self) -> None:
        forbidden = {
            "integration",
            "operator",
            "scripts/camera_bridge_va.py",
            "scripts/run_live.py",
            "src/thirdhand_va/bridge.py",
            "src/thirdhand_va/camera",
            "src/thirdhand_va/cli.py",
            "src/thirdhand_va/config.py",
            "src/thirdhand_va/contracts.py",
            "src/thirdhand_va/evaluation.py",
            "src/thirdhand_va/geometry",
            "src/thirdhand_va/handeye.py",
            "src/thirdhand_va/perception",
            "src/thirdhand_va/pipeline.py",
            "src/thirdhand_va/selection.py",
            "src/thirdhand_va/tracking",
            "src/thirdhand_va/visualization.py",
        }
        remaining = sorted(path for path in forbidden if Path(path).exists())
        self.assertEqual([], remaining)


if __name__ == "__main__":
    unittest.main()
