"""Prepare and verify a contained Startouch SDK runtime with safety enabled.

The host SDK is read only by the explicit offline preparation command.  The
real bridge imports only the content-addressed runtime inside this project.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping

import yaml


SOURCE_SCHEMA = "thirdhand-startouch-source-v1"
RUNTIME_SCHEMA = "thirdhand-startouch-runtime-v1"
PROFILE_ID = "thirdhand-conservative-safety-v1"
RUNTIME_MANIFEST_NAME = "runtime-manifest.json"

_REQUIRED_ASSETS = frozenset({
    "python_wrapper",
    "python_binding",
    "library",
    "source_config",
    "urdf",
    "gripper_permutation",
    "gripper_pi_b",
    "gripper_pi_fr",
})

_PROFILE_VALUES: Mapping[tuple[str, str], object] = {
    ("joint_trajectory", "max_acc_limits"): [
        35.0, 18.0, 87.0, 300.0, 300.0, 300.0,
    ],
    ("joint_trajectory", "max_jerk_limits"): [5000.0] * 6,
    ("joint_trajectory", "enforce_time_mode_acc_limit"): True,
    ("joint_trajectory", "enforce_time_mode_jerk_limit"): True,
    ("singularity_protection", "enabled"): True,
    ("singularity_protection", "wrist_warn_margin_rad"): 0.20,
    ("singularity_protection", "wrist_stop_margin_rad"): 0.06,
    ("singularity_protection", "shoulder_warn_radius_m"): 0.08,
    ("singularity_protection", "shoulder_stop_radius_m"): 0.03,
    ("singularity_protection", "elbow_warn_radius_rad"): 0.20,
    ("singularity_protection", "elbow_stop_radius_rad"): 0.07,
    ("singularity_protection", "jacobian_warn_sigma_min"): 0.025,
    ("singularity_protection", "jacobian_stop_sigma_min"): 0.008,
    ("singularity_protection", "jacobian_warn_condition"): 120.0,
    ("singularity_protection", "jacobian_stop_condition"): 350.0,
    ("singularity_protection", "jacobian_angular_scale_m"): 0.25,
    ("singularity_protection", "yellow_min_speed_scale"): 0.20,
    ("trajectory_safety", "enabled"): True,
    ("trajectory_safety", "joint_limit_warn_margin_rad"): 0.174533,
    ("trajectory_safety", "joint_limit_stop_margin_rad"): 0.05236,
    ("trajectory_safety", "tracking_error_warn_rad"): 0.10,
    ("trajectory_safety", "tracking_error_stop_rad"): 0.25,
    ("trajectory_safety", "tracking_error_stop_cycles"): 30,
    ("trajectory_safety", "velocity_warn_scale"): 1.10,
    ("trajectory_safety", "velocity_stop_scale"): 1.30,
    ("trajectory_safety", "acceleration_warn_scale"): 1.20,
    ("trajectory_safety", "acceleration_stop_scale"): 1.60,
    ("trajectory_safety", "jerk_warn_scale"): 1.50,
    ("trajectory_safety", "jerk_stop_scale"): 2.00,
    ("trajectory_safety", "derivative_stop_cycles"): 8,
    ("runtime_joint_safety", "enabled"): True,
    ("gripper_watchdog", "enabled"): True,
    ("gripper_watchdog", "command_period_ms"): 5.0,
    ("gripper_watchdog", "state_timeout_ms"): 100.0,
    ("gripper_watchdog", "position_error_warn_m"): 0.015,
    ("gripper_watchdog", "position_error_stop_m"): 0.035,
    ("gripper_watchdog", "position_error_stop_ms"): 500.0,
    ("self_collision", "enabled"): True,
    ("self_collision", "warn_distance_m"): 0.03,
    ("self_collision", "stop_distance_m"): 0.01,
}


class StartouchRuntimeError(RuntimeError):
    """A contained SDK asset or safety profile is absent or untrusted."""


@dataclass(frozen=True, slots=True)
class RuntimeValidation:
    root: Path
    interface_dir: Path
    library_dir: Path
    config_path: Path
    runtime_manifest_path: Path
    runtime_manifest_sha256: str
    profile_id: str
    sdk_version: str
    config_sha256: str
    reproducible_build_verified: bool


def _digest(path: Path) -> str:
    result = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _load_json(path: Path, error: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StartouchRuntimeError(error) from exc
    if not isinstance(value, dict):
        raise StartouchRuntimeError(error)
    return value


def _safe_child(root: Path, relative: object, error: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise StartouchRuntimeError(error)
    candidate = (root / relative).resolve()
    if root != candidate and root not in candidate.parents:
        raise StartouchRuntimeError(error)
    return candidate


def _source_description(path: Path) -> dict[str, Any]:
    payload = _load_json(path, "source_manifest_invalid")
    provenance = payload.get("artifact_provenance")
    license_evidence = payload.get("license_evidence")
    if (
        payload.get("schema") != SOURCE_SCHEMA
        or payload.get("sdk_version") != "0.1.7"
        or payload.get("license") != "MIT"
        or not str(payload.get("sdk_commit", "")).strip()
        or not isinstance(provenance, dict)
        or type(provenance.get("reproducible_build_verified")) is not bool
        or not isinstance(payload.get("assets"), dict)
        or not isinstance(license_evidence, dict)
        or license_evidence.get("declaration") != "MIT"
        or not isinstance(license_evidence.get("source_relative_path"), str)
        or not isinstance(license_evidence.get("sha256"), str)
        or len(license_evidence["sha256"]) != 64
    ):
        raise StartouchRuntimeError("source_manifest_invalid")
    if set(payload["assets"]) != _REQUIRED_ASSETS:
        raise StartouchRuntimeError("source_manifest_asset_set_invalid")
    return payload


def _profiled_config(source: Path) -> dict[str, Any]:
    try:
        config = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StartouchRuntimeError("source_safety_config_invalid") from exc
    if not isinstance(config, dict):
        raise StartouchRuntimeError("source_safety_config_invalid")
    try:
        if config["gripper_control"]["type"] != "TypeLJ":
            raise StartouchRuntimeError("source_gripper_type_mismatch")
        bodies = config["self_collision"]["bodies"]
        if not isinstance(bodies, list) or len(bodies) < 2:
            raise StartouchRuntimeError("source_collision_model_incomplete")
        for (section, key), value in _PROFILE_VALUES.items():
            target = config[section]
            if not isinstance(target, dict):
                raise KeyError(section)
            target[key] = value
    except KeyError as exc:
        raise StartouchRuntimeError("source_safety_config_incomplete") from exc
    return config


def _validate_profile(config: object) -> None:
    if not isinstance(config, dict):
        raise StartouchRuntimeError("runtime_safety_profile_invalid")
    try:
        if config["gripper_control"]["type"] != "TypeLJ":
            raise StartouchRuntimeError("runtime_gripper_type_mismatch")
        bodies = config["self_collision"]["bodies"]
        if not isinstance(bodies, list) or len(bodies) < 2:
            raise StartouchRuntimeError("runtime_collision_model_incomplete")
        for (section, key), expected in _PROFILE_VALUES.items():
            if config[section][key] != expected:
                raise StartouchRuntimeError("runtime_safety_profile_mismatch")
    except (KeyError, TypeError) as exc:
        raise StartouchRuntimeError("runtime_safety_profile_invalid") from exc


def prepare_startouch_runtime(
    source_sdk: Path, destination: Path, source_manifest: Path,
) -> Path:
    """Copy pinned assets and replace only the contained safety config."""

    source_root = Path(source_sdk).expanduser().resolve()
    target_root = Path(destination).expanduser().resolve()
    manifest_path = Path(source_manifest).expanduser().resolve()
    source = _source_description(manifest_path)
    if not source_root.is_dir():
        raise StartouchRuntimeError("source_sdk_missing")
    license_evidence = source["license_evidence"]
    license_path = _safe_child(
        source_root,
        license_evidence["source_relative_path"],
        "source_license_evidence_invalid",
    )
    if (
        not license_path.is_file()
        or _digest(license_path) != license_evidence["sha256"]
    ):
        raise StartouchRuntimeError("source_license_evidence_invalid")
    if target_root.name != "startouch_sdk":
        raise StartouchRuntimeError("runtime_root_name_invalid")
    target_root.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(
        prefix=".startouch-prepare-", dir=target_root.parent
    ))
    staging_root = staging_parent / "startouch_sdk"
    backup_root = staging_parent / "previous-startouch_sdk"
    try:
        staging_root.mkdir()
        runtime_assets: dict[str, dict[str, str]] = {}
        for name, record in source["assets"].items():
            if not isinstance(record, dict):
                raise StartouchRuntimeError("source_manifest_asset_invalid")
            source_path = _safe_child(
                source_root, record.get("source_relative_path"),
                "source_asset_path_invalid",
            )
            destination_path = _safe_child(
                staging_root, record.get("destination_relative_path"),
                "runtime_asset_path_invalid",
            )
            expected_hash = record.get("sha256")
            if (
                not source_path.is_file()
                or not isinstance(expected_hash, str)
                or _digest(source_path) != expected_hash
            ):
                raise StartouchRuntimeError(f"source_asset_hash_mismatch:{name}")
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination_path.with_suffix(destination_path.suffix + ".tmp")
            if record.get("transform") is None:
                shutil.copy2(source_path, temporary)
            elif record.get("transform") == PROFILE_ID:
                temporary.write_text(
                    yaml.safe_dump(_profiled_config(source_path), sort_keys=False),
                    encoding="utf-8",
                )
            else:
                raise StartouchRuntimeError("source_asset_transform_invalid")
            temporary.replace(destination_path)
            runtime_assets[name] = {
                "relative_path": destination_path.relative_to(
                    staging_root
                ).as_posix(),
                "sha256": _digest(destination_path),
            }

        payload = {
            "schema": RUNTIME_SCHEMA,
            "profile_id": PROFILE_ID,
            "sdk_version": source["sdk_version"],
            "sdk_commit": source["sdk_commit"],
            "license": source["license"],
            "artifact_provenance": source["artifact_provenance"],
            "source_manifest_sha256": _digest(manifest_path),
            "assets": runtime_assets,
        }
        staging_manifest = staging_root / RUNTIME_MANIFEST_NAME
        staging_manifest.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        validate_startouch_runtime(staging_root, manifest_path)

        if target_root.exists():
            if not target_root.is_dir() or target_root.is_symlink():
                raise StartouchRuntimeError("runtime_destination_invalid")
            target_root.replace(backup_root)
        installed = False
        try:
            staging_root.replace(target_root)
            installed = True
            validate_startouch_runtime(target_root, manifest_path)
        except BaseException:
            failed_root = staging_parent / "failed-startouch-sdk"
            if installed and target_root.exists():
                target_root.replace(failed_root)
            if backup_root.exists():
                backup_root.replace(target_root)
            raise
        return target_root / RUNTIME_MANIFEST_NAME
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def validate_startouch_runtime(
    runtime_root: Path, source_manifest: Path,
) -> RuntimeValidation:
    """Validate hashes and exact enabled safety values without hardware."""

    root = Path(runtime_root).expanduser().resolve()
    source_path = Path(source_manifest).expanduser().resolve()
    if root.name != "startouch_sdk":
        raise StartouchRuntimeError("runtime_root_name_invalid")
    source = _source_description(source_path)
    manifest_path = root / RUNTIME_MANIFEST_NAME
    payload = _load_json(manifest_path, "runtime_manifest_invalid")
    if (
        payload.get("schema") != RUNTIME_SCHEMA
        or payload.get("profile_id") != PROFILE_ID
        or payload.get("sdk_version") != source["sdk_version"]
        or payload.get("sdk_commit") != source["sdk_commit"]
        or payload.get("license") != source["license"]
        or payload.get("artifact_provenance") != source["artifact_provenance"]
        or payload.get("source_manifest_sha256") != _digest(source_path)
        or not isinstance(payload.get("assets"), dict)
        or set(payload["assets"]) != _REQUIRED_ASSETS
    ):
        raise StartouchRuntimeError("runtime_manifest_invalid")
    paths: dict[str, Path] = {}
    for name, record in payload["assets"].items():
        if not isinstance(record, dict):
            raise StartouchRuntimeError("runtime_manifest_asset_invalid")
        asset_path = _safe_child(
            root, record.get("relative_path"), "runtime_asset_path_invalid"
        )
        expected_hash = record.get("sha256")
        if (
            not asset_path.is_file()
            or not isinstance(expected_hash, str)
            or _digest(asset_path) != expected_hash
        ):
            raise StartouchRuntimeError(f"runtime_asset_hash_mismatch:{name}")
        paths[name] = asset_path
    expected_files = {
        RUNTIME_MANIFEST_NAME,
        *(path.relative_to(root).as_posix() for path in paths.values()),
    }
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual_files != expected_files:
        raise StartouchRuntimeError("runtime_unmanifested_asset")
    config_path = paths["source_config"]
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StartouchRuntimeError("runtime_safety_config_invalid") from exc
    _validate_profile(config)
    return RuntimeValidation(
        root=root,
        interface_dir=paths["python_wrapper"].parent,
        library_dir=paths["library"].parent,
        config_path=config_path,
        runtime_manifest_path=manifest_path,
        runtime_manifest_sha256=_digest(manifest_path),
        profile_id=PROFILE_ID,
        sdk_version=str(payload["sdk_version"]),
        config_sha256=_digest(config_path),
        reproducible_build_verified=bool(
            source["artifact_provenance"]["reproducible_build_verified"]
        ),
    )


def runtime_library_environment(
    runtime_root: Path, inherited_library_path: str | None = None,
) -> str:
    """Return an LD_LIBRARY_PATH with the contained library first."""

    library_dir = Path(runtime_root).expanduser().resolve() / "src"
    inherited = inherited_library_path or ""
    return os.pathsep.join(
        value for value in (str(library_dir), inherited) if value
    )


def assert_loaded_startouch_library(
    runtime_root: Path, *, maps_text: str | None = None,
) -> None:
    """Prove the process mapped the contained library, not a host copy."""

    expected = Path(runtime_root).expanduser().resolve() / "src/libstartouch.so"
    if maps_text is None:
        try:
            maps_text = Path("/proc/self/maps").read_text(encoding="utf-8")
        except OSError as exc:
            raise StartouchRuntimeError("process_maps_unavailable") from exc
    if not any(
        line.rstrip().endswith(str(expected)) for line in maps_text.splitlines()
    ):
        raise StartouchRuntimeError("runtime_library_not_loaded")


__all__ = [
    "PROFILE_ID",
    "RuntimeValidation",
    "StartouchRuntimeError",
    "assert_loaded_startouch_library",
    "prepare_startouch_runtime",
    "runtime_library_environment",
    "validate_startouch_runtime",
]
