import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = (
    ROOT / "src" / "uiea_thirdhand_vla" / "orchestration" / "runtime",
    ROOT / "src" / "uiea_thirdhand_vla" / "orchestration" / "shadow",
)
FORBIDDEN_IMPORTS = {
    "can",
    "cv2",
    "pyrealsense2",
    "rclpy",
    "rospy",
    "socket",
    "startouchclass",
    "subprocess",
}


def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0].lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0].lower())
    return roots


def test_runtime_and_shadow_packages_have_no_hardware_process_or_camera_imports():
    paths = tuple(path for package in PACKAGES for path in package.glob("*.py"))
    imports = set().union(*(imported_roots(path) for path in paths))

    assert imports.isdisjoint(FORBIDDEN_IMPORTS)


def test_shadow_sources_offer_no_environment_real_mode_escape_hatch():
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for package in PACKAGES
        for path in package.glob("*.py")
    )

    assert "STARTOUCH_REAL" not in sources
    assert "robot_execution_enabled: Literal[True]" not in sources
    assert 'ExecutorKind.REAL' not in sources
