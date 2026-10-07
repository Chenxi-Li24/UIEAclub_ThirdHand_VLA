import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import APP_ROOT, PROJECT_ROOT, load_config, resolve_project_path
from dummy.follow3d.handeye_projector import FollowHandEyeProjector
from dummy.follow3d.mink_backend import MinkLookAtController
from dummy.workspace_guard import WorkspaceGuard
from dummy.yolo_person_detector import YoloPersonDetector


def test_default_resource_paths_resolve_against_current_checkout(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config = load_config()
    urdf = PROJECT_ROOT / "assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf"
    for section in ("follow_handeye", "workspace_guard", "mink_lookat"):
        config[section]["enabled"] = False
    projector = FollowHandEyeProjector(config)
    guard = WorkspaceGuard(config)
    mink = MinkLookAtController(config)
    assert projector.urdf_path == guard.urdf_path == Path(mink.model_path) == urdf
    assert projector.calibration_path == PROJECT_ROOT / "skills/manipulation/bottlegrasp/configs/calibration/lumos-handeye.pending.json"
    assert Path(config["vision_service"]["mediapipe_face_model_path"]) == APP_ROOT / "models/blaze_face_short_range.tflite"


def test_yolo_default_is_project_local_and_independent_of_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    detector = YoloPersonDetector({"vision_service": {"yolo_person_enabled": False}})
    assert Path(detector.model_path) == PROJECT_ROOT / "local/models/vision/yolov8n.pt"


def test_configured_yolo_relative_path_uses_project_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    detector = YoloPersonDetector({"vision_service": {
        "yolo_person_enabled": False, "yolo_person_model_path": "local/models/vision/person.pt",
    }})
    assert Path(detector.model_path) == PROJECT_ROOT / "local/models/vision/person.pt"


def test_explicit_absolute_resource_path_is_preserved(tmp_path):
    path = tmp_path / "person.pt"
    assert resolve_project_path(path) == path
    detector = YoloPersonDetector({"vision_service": {
        "yolo_person_enabled": False, "yolo_person_model_path": str(path),
    }})
    assert Path(detector.model_path) == path
    mink = MinkLookAtController({"mink_lookat": {"model_path": str(path)}})
    assert Path(mink.model_path) == path


def test_missing_yolo_weights_do_not_trigger_download(monkeypatch, tmp_path):
    class DownloadForbidden:
        def YOLO(self, _path):
            raise AssertionError("missing model must not trigger Ultralytics loading")

    monkeypatch.setitem(sys.modules, "ultralytics", DownloadForbidden())
    detector = YoloPersonDetector({"vision_service": {
        "yolo_person_model_path": str(tmp_path / "missing.pt"),
    }})
    assert not detector.available
    assert "YOLO model not found" in detector.error


def test_web_vision_override_uses_one_shared_service(monkeypatch):
    monkeypatch.setenv("DUMMY_VISION_HTTP_URL", "http://127.0.0.1:13100")
    vision = load_config()["vision_service"]
    assert vision["mjpeg_url"] == "http://127.0.0.1:13100/camera/xvisio/raw"
    assert vision["health_url"] == "http://127.0.0.1:13100/health"
    assert vision["observation_url"] == "http://127.0.0.1:13100/api/vision/person-follow/observation"
