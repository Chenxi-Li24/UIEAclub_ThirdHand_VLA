from pathlib import Path
import os
import yaml
from urllib.parse import urljoin


APP_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = APP_ROOT.parents[1]
DEFAULT_CONFIG = APP_ROOT / "configs" / "dum_e_touch_r1.yaml"


def resolve_project_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_config(path=None):
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with cfg_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    vision = config.get("vision_service", {})
    model_path = vision.get("mediapipe_face_model_path")
    if model_path:
        resolved = Path(model_path)
        if not resolved.is_absolute():
            vision["mediapipe_face_model_path"] = str(APP_ROOT / resolved)

    urdf = os.environ.get("DUMMY_URDF_PATH")
    if urdf:
        for section, key in (("workspace_guard", "urdf_path"), ("follow_handeye", "urdf_path"),
                             ("mink_lookat", "model_path")):
            config.setdefault(section, {})[key] = urdf
    for variable, key in (("DUMMY_FACE_MODEL", "mediapipe_face_model_path"),
                          ("DUMMY_YOLO_MODEL", "yolo_person_model_path")):
        if variable in os.environ:
            vision[key] = os.environ[variable]
    if "DUMMY_SPEECH_WS" in os.environ:
        config.setdefault("wake_word", {})["speech_ws_url"] = os.environ["DUMMY_SPEECH_WS"]
    if "DUMMY_VISION_HTTP_URL" in os.environ:
        base = os.environ["DUMMY_VISION_HTTP_URL"]
        for key, route in (("mjpeg_url", "/camera/xvisio/raw"), ("health_url", "/health"),
                           ("observation_url", "/api/vision/person-follow/observation")):
            vision[key] = urljoin(base, route)

    return config
