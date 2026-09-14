"""Offline tests for the content-addressed Startouch safety runtime."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest
import yaml

from native.startouch.vendor_runtime import (
    PROFILE_ID,
    StartouchRuntimeError,
    assert_loaded_startouch_library,
    prepare_startouch_runtime,
    runtime_library_environment,
    validate_startouch_runtime,
)


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _source_sdk(
    tmp_path: Path, *, reproducible_build_verified: bool = True,
) -> tuple[Path, Path]:
    source = tmp_path / "source-sdk"
    license_path = source / "pyproject.toml"
    license_path.parent.mkdir(parents=True, exist_ok=True)
    license_path.write_text(
        '[project]\nlicense = {text = "MIT"}\n', encoding="utf-8"
    )
    assets = {
        "python_wrapper": ("interface_py/startouchclass.py", b"wrapper"),
        "python_binding": ("interface_py/startouch.fake.so", b"binding"),
        "library": ("src/libstartouch.so", b"library"),
        "urdf": ("src/config/FastTouchV2.SLDASM.urdf", b"<robot/>"),
        "gripper_permutation": (
            "src/param_csv_gripper/permutationMatrix.csv", b"permutation",
        ),
        "gripper_pi_b": ("src/param_csv_gripper/pi_b.csv", b"pi-b"),
        "gripper_pi_fr": ("src/param_csv_gripper/pi_fr.csv", b"pi-fr"),
    }
    for relative, content in assets.values():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    config_path = source / "src/config/robot_kinematics.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "joint_trajectory": {
                    "max_acc_limits": [500.0] * 6,
                    "max_jerk_limits": [1_000_000.0] * 6,
                    "enforce_time_mode_acc_limit": False,
                    "enforce_time_mode_jerk_limit": False,
                },
                "singularity_protection": {"enabled": False},
                "trajectory_safety": {
                    "enabled": False,
                    "derivative_stop_cycles": 2000,
                },
                "runtime_joint_safety": {"enabled": False},
                "gripper_watchdog": {
                    "enabled": False,
                    "position_error_stop_ms": 50_000.0,
                },
                "gripper_control": {"type": "TypeLJ"},
                "self_collision": {
                    "enabled": False,
                    "warn_distance_m": 0.002,
                    "stop_distance_m": 0.0,
                    "bodies": [
                        {"name": "a", "link": "link1", "type": "capsule"},
                        {"name": "b", "link": "link2", "type": "capsule"},
                    ],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    manifest_assets = {
        name: {
            "source_relative_path": relative,
            "destination_relative_path": relative.replace(
                "src/param_csv_gripper", "param_csv_gripper"
            ),
            "sha256": _digest(source / relative),
        }
        for name, (relative, _) in assets.items()
    }
    manifest_assets["source_config"] = {
        "source_relative_path": "src/config/robot_kinematics.yaml",
        "destination_relative_path": "src/config/robot_kinematics.yaml",
        "sha256": _digest(config_path),
        "transform": "thirdhand-conservative-safety-v1",
    }
    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "thirdhand-startouch-source-v1",
                "sdk_version": "0.1.7",
                "sdk_commit": "fixture-commit",
                "license": "MIT",
                "license_evidence": {
                    "declaration": "MIT",
                    "sha256": _digest(license_path),
                    "source_relative_path": "pyproject.toml",
                },
                "artifact_provenance": {
                    "kind": "clean-reproducible-build",
                    "reproducible_build_verified": reproducible_build_verified,
                },
                "assets": manifest_assets,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return source, manifest


def test_prepare_rejects_changed_license_evidence(tmp_path: Path) -> None:
    source, source_manifest = _source_sdk(tmp_path)
    (source / "pyproject.toml").write_text(
        '[project]\nlicense = {text = "UNKNOWN"}\n', encoding="utf-8"
    )

    with pytest.raises(StartouchRuntimeError, match="source_license_evidence_invalid"):
        prepare_startouch_runtime(
            source, tmp_path / "startouch_sdk", source_manifest
        )


def test_prepare_runtime_enables_exact_conservative_safety_profile(
    tmp_path: Path,
) -> None:
    source, source_manifest = _source_sdk(tmp_path)
    destination = tmp_path / "startouch_sdk"

    runtime_manifest = prepare_startouch_runtime(
        source, destination, source_manifest
    )
    validation = validate_startouch_runtime(destination, source_manifest)
    config = yaml.safe_load(validation.config_path.read_text(encoding="utf-8"))

    assert runtime_manifest == destination / "runtime-manifest.json"
    assert validation.profile_id == PROFILE_ID == "thirdhand-conservative-safety-v1"
    assert config["joint_trajectory"]["enforce_time_mode_acc_limit"] is True
    assert config["joint_trajectory"]["enforce_time_mode_jerk_limit"] is True
    assert config["singularity_protection"]["enabled"] is True
    assert config["trajectory_safety"]["enabled"] is True
    assert config["trajectory_safety"]["joint_limit_stop_margin_rad"] == 0.05236
    assert config["runtime_joint_safety"]["enabled"] is True
    assert config["gripper_watchdog"]["enabled"] is True
    assert config["self_collision"]["enabled"] is True


def test_runtime_validation_rejects_tampering_and_shadow_modules(
    tmp_path: Path,
) -> None:
    source, source_manifest = _source_sdk(tmp_path)
    destination = tmp_path / "startouch_sdk"
    prepare_startouch_runtime(source, destination, source_manifest)
    config_path = destination / "src/config/robot_kinematics.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["self_collision"]["enabled"] = False
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(StartouchRuntimeError, match="runtime_asset_hash_mismatch"):
        validate_startouch_runtime(destination, source_manifest)

    prepare_startouch_runtime(source, destination, source_manifest)
    (destination / "interface_py/startouch.py").write_text(
        "raise RuntimeError('shadowed')\n", encoding="utf-8"
    )
    with pytest.raises(StartouchRuntimeError, match="runtime_unmanifested_asset"):
        validate_startouch_runtime(destination, source_manifest)


def test_runtime_preserves_unverified_binary_provenance(tmp_path: Path) -> None:
    source, source_manifest = _source_sdk(
        tmp_path, reproducible_build_verified=False
    )
    destination = tmp_path / "startouch_sdk"

    prepare_startouch_runtime(source, destination, source_manifest)
    validation = validate_startouch_runtime(destination, source_manifest)

    assert validation.reproducible_build_verified is False


def test_runtime_library_must_be_loaded_from_contained_root(tmp_path: Path) -> None:
    runtime = tmp_path / "startouch_sdk"
    library = runtime / "src/libstartouch.so"
    library.parent.mkdir(parents=True)
    library.write_bytes(b"library")

    assert runtime_library_environment(runtime, "/opt/other") == (
        f"{runtime.resolve() / 'src'}:/opt/other"
    )
    assert_loaded_startouch_library(
        runtime,
        maps_text=f"7f00-7f01 r-xp 0000 00:00 0 {library.resolve()}\n",
    )
    with pytest.raises(StartouchRuntimeError, match="runtime_library_not_loaded"):
        assert_loaded_startouch_library(
            runtime,
            maps_text="7f00-7f01 r-xp 0000 00:00 0 /host/libstartouch.so\n",
        )
