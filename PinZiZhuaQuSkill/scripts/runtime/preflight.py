#!/usr/bin/env python3
"""Read-only runtime checks for the bottle V+A skill.

This module deliberately imports no camera, model, network, or robot adapter.
It is safe to run from VS Code before any live-hardware session.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
from typing import Final

import yaml


CODE_ROOT = Path(__file__).resolve().parents[2]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from native.startouch.vendor_runtime import (  # noqa: E402
    StartouchRuntimeError,
    validate_startouch_runtime,
)


EXPECTED_DISTRIBUTIONS: Final[dict[str, str]] = {
    "numpy": "1.26.4",
    "PyYAML": "6.0.2",
    "opencv-python": "4.11.0.86",
    "Pillow": "12.2.0",
    "pytest": "8.4.2",
    "torch": "2.7.0+cu128",
    "transformers": "4.56.2",
    "norfair": "2.3.0",
}


def _installed_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _cached_model_snapshot(
    cache_dir: Path, model_id: object, revision: object
) -> tuple[Path, Path] | None:
    if (
        not isinstance(model_id, str)
        or not model_id
        or "/" not in model_id
        or not isinstance(revision, str)
        or len(revision) != 40
        or any(character not in "0123456789abcdef" for character in revision)
    ):
        return None
    repository = cache_dir / ("models--" + model_id.replace("/", "--"))
    snapshot = repository / "snapshots" / revision
    if not snapshot.is_dir():
        return None
    has_config = (snapshot / "config.json").is_file()
    has_processor = any(
        (snapshot / name).is_file()
        for name in (
            "preprocessor_config.json",
            "processor_config.json",
            "video_preprocessor_config.json",
        )
    )
    weight = next(
        (
            snapshot / name
            for name in (
                "model.safetensors",
                "pytorch_model.bin",
                "sam2.1_hiera_tiny.pt",
            )
            if (snapshot / name).is_file()
        ),
        None,
    )
    if has_config and has_processor and weight is not None:
        return snapshot.resolve(), weight.resolve()
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _model_cache_report(
    root: Path, blockers: list[str]
) -> tuple[dict[str, str | None], dict[str, dict[str, str | bool | None]]]:
    config_path = root / "configs/vision.yaml"
    if not config_path.is_file():
        blockers.append("vision_config_missing")
        return {}, {}
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        blockers.append("vision_config_invalid")
        return {}, {}
    if not isinstance(raw, dict):
        blockers.append("vision_config_invalid")
        return {}, {}
    hf_home = raw.get("hf_home")
    if not isinstance(hf_home, str) or not hf_home:
        blockers.append("model_cache_path_unconfigured")
        return {}, {}
    cache_home = Path(hf_home)
    if not cache_home.is_absolute():
        cache_home = (root / cache_home).resolve()
    cache_dir = cache_home / "hub"
    report: dict[str, str | None] = {}
    evidence: dict[str, dict[str, str | bool | None]] = {}
    for role, field, revision_field, hash_field in (
        (
            "grounding", "grounding_model", "grounding_revision",
            "grounding_weights_sha256",
        ),
        ("sam", "sam_model", "sam_revision", "sam_weights_sha256"),
    ):
        model_id = raw.get(field)
        revision = raw.get(revision_field)
        expected_hash = raw.get(hash_field)
        located = _cached_model_snapshot(cache_dir, model_id, revision)
        key = str(model_id) if isinstance(model_id, str) else field
        report[key] = None if located is None else str(located[0])
        actual_hash = None if located is None else _sha256_file(located[1])
        verified = bool(
            located is not None
            and isinstance(expected_hash, str)
            and actual_hash == expected_hash
        )
        evidence[role] = {
            "model_id": key,
            "revision": revision if isinstance(revision, str) else None,
            "weights_sha256": actual_hash,
            "verified": verified,
        }
        if located is None:
            blockers.append(f"model_cache_missing:{role}:{key}")
        elif not verified:
            blockers.append(f"model_weight_hash_mismatch:{role}:{key}")
    return report, evidence


def _startouch_runtime_report(
    root: Path, blockers: list[str],
) -> dict[str, object]:
    config_path = root / "configs/action.yaml"
    if not config_path.is_file():
        blockers.append("action_config_missing")
        return {}
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        robot = raw["robot"]
        runtime_root = (config_path.parent / robot["runtime_root"]).resolve()
        source_manifest = (
            config_path.parent / robot["source_manifest"]
        ).resolve()
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        blockers.append("action_config_invalid")
        return {}
    try:
        validation = validate_startouch_runtime(
            runtime_root, source_manifest
        )
    except StartouchRuntimeError as error:
        blockers.append(f"startouch_runtime_invalid:{error}")
        return {
            "runtime_root": str(runtime_root),
            "validated": False,
        }
    manifest_id = "sha256:" + validation.runtime_manifest_sha256
    identity_matches = (
        robot.get("safety_profile_id") == validation.profile_id
        and robot.get("safety_config_sha256") == validation.config_sha256
        and robot.get("runtime_manifest_id") == manifest_id
    )
    if not identity_matches:
        blockers.append("startouch_runtime_identity_mismatch")
    if not validation.reproducible_build_verified:
        blockers.append("startouch_binary_provenance_unverified")
    if raw.get("execution_enabled") is not True:
        blockers.append("action_execution_disabled")
    grasp_offset_validated = (
        isinstance(raw.get("grasp"), dict)
        and raw["grasp"].get("offset_validated") is True
    )
    place_validated = (
        isinstance(raw.get("place"), dict)
        and raw["place"].get("validated") is True
    )
    if not grasp_offset_validated:
        blockers.append("grasp_offset_not_validated")
    if not place_validated:
        blockers.append("place_not_validated")

    stop_margin = robot.get("joint_limit_stop_margin_deg")
    limits = robot.get("joint_limits_deg")
    presets = robot.get("presets")
    violations: list[str] = []
    if (
        isinstance(stop_margin, (int, float))
        and isinstance(limits, list)
        and len(limits) == 6
        and isinstance(presets, dict)
    ):
        for name, joints in presets.items():
            if not isinstance(joints, list) or len(joints) != 6:
                continue
            for index, (joint, bounds) in enumerate(zip(joints, limits)):
                if (
                    isinstance(joint, (int, float))
                    and isinstance(bounds, list)
                    and len(bounds) == 2
                    and (
                        joint - bounds[0] <= stop_margin
                        or bounds[1] - joint <= stop_margin
                    )
                ):
                    violation = f"{name}:joint_{index + 1}"
                    violations.append(violation)
                    blockers.append(
                        "robot_preset_inside_joint_stop_margin:" + violation
                    )
    return {
        "config_sha256": validation.config_sha256,
        "identity_matches_config": identity_matches,
        "preset_stop_margin_violations": violations,
        "profile_id": validation.profile_id,
        "grasp_offset_validated": grasp_offset_validated,
        "place_validated": place_validated,
        "real_start_allowed": (
            identity_matches
            and validation.reproducible_build_verified
            and raw.get("execution_enabled") is True
            and grasp_offset_validated
            and place_validated
            and not violations
        ),
        "reproducible_build_verified": (
            validation.reproducible_build_verified
        ),
        "runtime_manifest_id": manifest_id,
        "runtime_root": str(validation.root),
        "validated": True,
    }


def collect_report(project_root: Path) -> dict[str, object]:
    """Return deterministic readiness evidence without touching hardware."""
    root = Path(project_root).resolve()
    blockers: list[str] = []
    versions: dict[str, str | None] = {}

    executable = root / "build/vision/xvisio_rgbd_stream/xvisio_rgbd_stream"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        blockers.append("xvisio_executable_missing")

    for distribution, expected in EXPECTED_DISTRIBUTIONS.items():
        installed = _installed_version(distribution)
        versions[distribution] = installed
        if installed != expected:
            actual = installed if installed is not None else "missing"
            blockers.append(
                f"dependency_version_mismatch:{distribution}:{actual}!={expected}"
            )
    model_cache, model_evidence = _model_cache_report(root, blockers)
    startouch_runtime = _startouch_runtime_report(root, blockers)

    return {
        "schema": "thirdhand-va-preflight-v1",
        "project_root": str(root),
        "ready": not blockers,
        "blockers": blockers,
        "versions": versions,
        "model_cache": model_cache,
        "model_evidence": model_evidence,
        "startouch_runtime": startouch_runtime,
        "xvisio_executable": str(executable),
        "hardware_touched": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = collect_report(args.project_root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        state = "ready" if report["ready"] else "blocked"
        print(f"VA runtime preflight: {state}")
        for blocker in report["blockers"]:
            print(f"- {blocker}")
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
