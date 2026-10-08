"""Offline contracts for the deployment-to-main source migration."""
import importlib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "apps/dummy/experiments/deployment_20260915"
sys.path.insert(0, str(EXPERIMENT / "src"))


def test_legacy_namespace_resolves_resources_from_project_root():
    config = importlib.import_module("dummy_legacy.config")
    loaded = config.load_config()
    assert config.PROJECT_ROOT == ROOT
    assert loaded["vision_service"]["mediapipe_face_model_path"] == str(
        ROOT / "apps/dummy/models/blaze_face_short_range.tflite"
    )
    assert Path(loaded["workspace_guard"]["urdf_path"]).is_file()


def test_legacy_yolo_default_is_project_local_without_loading_model():
    detector = importlib.import_module("dummy_legacy.yolo_person_detector")
    instance = detector.YoloPersonDetector({"vision_service": {"yolo_person_enabled": False}})
    assert Path(instance.model_path) == ROOT / "local/models/vision/yolov8n.pt"


def test_fixed_tcp_client_uses_existing_robot_owner_without_constructing_arm():
    source = (ROOT / "apps/fixed_tcp_demo/fixed_tcp_demo.py").read_text()
    assert "from websockets.sync.client import connect" in source
    assert "ws://127.0.0.1:3000/ws" in source
    assert "SingleArm" not in source
    assert not (ROOT / "apps/fixed_tcp_demo/arm.py").exists()


def test_default_runtime_does_not_load_experiments_or_fixed_tcp():
    paths = list((ROOT / "configs/runtime").glob("*.json"))
    assert paths
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "experiments/deployment_20260915" not in text
        assert "fixed_tcp_demo" not in text
