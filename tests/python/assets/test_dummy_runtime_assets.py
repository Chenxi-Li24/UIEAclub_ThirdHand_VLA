import json
from pathlib import Path
import sys

import pytest

from tools.assets.restore_runtime_assets import verify


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/dummy/src"))

from dummy.config import load_config, resolve_project_path


@pytest.mark.parametrize("key", ["yunet_face_model_path", "yolo_person_model_path"])
def test_default_dummy_model_is_bundled_and_matches_manifest(monkeypatch, tmp_path, key):
    monkeypatch.delenv("DUMMY_YUNET_MODEL", raising=False)
    monkeypatch.delenv("DUMMY_YOLO_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    config = load_config()
    model = resolve_project_path(config["vision_service"][key])
    name = model.relative_to(ROOT).as_posix()
    manifest = json.loads(
        (ROOT / "configs/assets/runtime-assets.json").read_text(encoding="utf-8")
    )
    entries = {entry["path"]: entry for entry in manifest["files"]}
    assert name in entries, f"default Dummy model missing from asset manifest: {name}"
    verify(model, entries[name])
