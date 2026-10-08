from pathlib import Path
import yaml


APP_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = APP_ROOT.parents[3]
DEFAULT_CONFIG = APP_ROOT / "configs" / "dum_e_touch_r1.yaml"


def load_config(path=None):
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with cfg_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    for section, keys in {
        "vision_service": ("mediapipe_face_model_path", "yolo_person_model_path"),
        "follow_handeye": ("calibration_path", "urdf_path"),
        "workspace_guard": ("urdf_path",),
        "mink_lookat": ("model_path",),
    }.items():
        options = config.get(section, {})
        for key in keys:
            value = options.get(key)
            if value and not Path(value).is_absolute():
                options[key] = str(PROJECT_ROOT / value)

    return config
