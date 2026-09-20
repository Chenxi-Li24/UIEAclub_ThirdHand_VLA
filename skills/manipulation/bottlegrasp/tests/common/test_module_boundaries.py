import ast
from pathlib import Path
import unittest


class ModuleBoundaryTests(unittest.TestCase):
    def test_public_domains_are_importable(self):
        import thirdhand_va.action  # noqa: F401
        import thirdhand_va.common  # noqa: F401
        import thirdhand_va.vision

        self.assertEqual(thirdhand_va.vision.VisionPipeline.__name__, "VisionPipeline")

    def test_vision_does_not_import_action(self):
        root = Path("src/thirdhand_va/vision")
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported_from = {
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            }
            imported_directly = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            imported = imported_from | imported_directly
            self.assertFalse(
                any(name.startswith("thirdhand_va.action") for name in imported),
                f"Vision must not depend on Action: {path}",
            )

    def test_action_does_not_import_vision_implementation(self):
        root = Path("src/thirdhand_va/action")
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = {
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            } | {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            self.assertFalse(
                any(name.startswith("thirdhand_va.vision") for name in imported),
                f"Action must consume contracts, not Vision internals: {path}",
            )


if __name__ == "__main__":
    unittest.main()
