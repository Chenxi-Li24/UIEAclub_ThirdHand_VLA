import importlib.util
import hashlib
from pathlib import Path
from types import SimpleNamespace

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_preflight_module():
    path = ROOT / "scripts/runtime/preflight.py"
    spec = importlib.util.spec_from_file_location("thirdhand_va_preflight", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load preflight module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preflight_reports_missing_assets_without_opening_hardware(
    tmp_path: Path,
) -> None:
    preflight = load_preflight_module()

    report = preflight.collect_report(tmp_path)

    assert report["hardware_touched"] is False
    assert report["ready"] is False
    assert "xvisio_executable_missing" in report["blockers"]
    assert "vision_config_missing" in report["blockers"]
    assert "action_config_missing" in report["blockers"]
    assert report["model_cache"] == {}
    assert report["startouch_runtime"] == {}


def test_preflight_report_is_json_safe(tmp_path: Path) -> None:
    import json

    preflight = load_preflight_module()

    encoded = json.dumps(preflight.collect_report(tmp_path), sort_keys=True)

    assert '"hardware_touched": false' in encoded


def test_preflight_requires_exact_model_revision_and_weight_hash(tmp_path: Path) -> None:
    preflight = load_preflight_module()
    cache = tmp_path / "cache"
    revision = "1" * 40
    weight = b"pinned-model-weight"
    digest = "sha256:" + hashlib.sha256(weight).hexdigest()
    snapshot = cache / "hub/models--org--model/snapshots" / revision
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(weight)
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config = {
        "hf_home": str(cache),
        "grounding_model": "org/model",
        "grounding_revision": revision,
        "grounding_weights_sha256": digest,
        "sam_model": "org/model",
        "sam_revision": revision,
        "sam_weights_sha256": digest,
    }
    (config_dir / "vision.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    blockers: list[str] = []

    model_cache, evidence = preflight._model_cache_report(tmp_path, blockers)

    assert blockers == []
    assert model_cache["org/model"] == str(snapshot.resolve())
    assert evidence["grounding"]["weights_sha256"] == digest
    config["sam_weights_sha256"] = "sha256:" + "0" * 64
    (config_dir / "vision.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    blockers = []
    preflight._model_cache_report(tmp_path, blockers)
    assert "model_weight_hash_mismatch:sam:org/model" in blockers


def test_startouch_preflight_reports_unvalidated_action_gates(
    tmp_path: Path, monkeypatch,
) -> None:
    preflight = load_preflight_module()
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "action.yaml").write_text(
        yaml.safe_dump({
            "execution_enabled": True,
            "grasp": {"offset_validated": False},
            "place": {"validated": False},
            "robot": {
                "runtime_root": "../build/startouch_runtime/startouch_sdk",
                "source_manifest": "../native/startouch/startouch_source.json",
                "safety_profile_id": "thirdhand-conservative-safety-v1",
                "safety_config_sha256": "config-hash",
                "runtime_manifest_id": "sha256:manifest-hash",
                "joint_limit_stop_margin_deg": 3.0,
                "joint_limits_deg": [[-10, 10]] * 6,
                "presets": {"home": [0, 0, 0, 0, 0, 0]},
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        preflight,
        "validate_startouch_runtime",
        lambda *_args: SimpleNamespace(
            config_sha256="config-hash",
            profile_id="thirdhand-conservative-safety-v1",
            reproducible_build_verified=True,
            root=tmp_path / "build/startouch_runtime/startouch_sdk",
            runtime_manifest_sha256="manifest-hash",
        ),
    )
    blockers: list[str] = []

    runtime = preflight._startouch_runtime_report(tmp_path, blockers)

    assert "grasp_offset_not_validated" in blockers
    assert "place_not_validated" in blockers
    assert runtime["real_start_allowed"] is False
