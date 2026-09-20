from pathlib import Path
import yaml


APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = APP_ROOT / "configs" / "dum_e_touch_r1.yaml"


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

    return config
