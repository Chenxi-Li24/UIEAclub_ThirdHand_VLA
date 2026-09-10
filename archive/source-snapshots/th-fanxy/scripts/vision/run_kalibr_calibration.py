#!/usr/bin/env python3
"""Preflight or run the official Kalibr dual-camera calibration commands."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def build_commands(
    dataset: Path | str,
    target: Path | str,
    output: Path | str,
) -> tuple[list[str], list[str]]:
    dataset_path = Path(dataset).resolve()
    target_path = Path(target).resolve()
    output_path = Path(output).resolve()
    bag_path = output_path / "dual-camera.bag"
    return (
        [
            "kalibr_bagcreater",
            "--folder",
            str(dataset_path),
            "--output-bag",
            str(bag_path),
        ],
        [
            "kalibr_calibrate_cameras",
            "--bag",
            str(bag_path),
            "--topics",
            "/cam0/image_raw",
            "/cam1/image_raw",
            "--models",
            "eucm-none",
            "pinhole-none",
            "--target",
            str(target_path),
            "--dont-show-report",
        ],
    )


def _validate_capture(dataset: Path, target: Path) -> None:
    manifest_path = dataset / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Kalibr capture manifest cannot be parsed") from exc
    if manifest.get("kalibr_topics") != ["/cam0/image_raw", "/cam1/image_raw"]:
        raise ValueError("Kalibr capture camera order is invalid")
    if manifest.get("kalibr_models") != ["eucm-none", "pinhole-none"]:
        raise ValueError("Kalibr capture models are invalid")
    if manifest.get("purpose") != "fit":
        raise ValueError("Kalibr fitting requires a purpose=fit dataset")
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) < 20:
        raise ValueError("Kalibr capture requires at least 20 pairs")
    if not target.resolve(strict=True).is_file():
        raise ValueError("Kalibr target is missing")


def run_kalibr(
    dataset: Path | str,
    target: Path | str,
    output: Path | str,
    *,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    dataset_path = Path(dataset).resolve(strict=True)
    target_path = Path(target).resolve(strict=True)
    output_path = Path(output).resolve()
    _validate_capture(dataset_path, target_path)
    commands = build_commands(dataset_path, target_path, output_path)
    if dry_run:
        return commands
    missing = [command[0] for command in commands if shutil.which(command[0]) is None]
    if missing:
        raise RuntimeError(
            "official Kalibr commands are not installed: " + ", ".join(sorted(missing))
        )
    output_path.mkdir(parents=True, exist_ok=True)
    for command in commands:
        subprocess.run(command, cwd=output_path, check=True)
    return commands


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    commands = run_kalibr(
        arguments.dataset,
        arguments.target,
        arguments.output,
        dry_run=arguments.dry_run,
    )
    for command in commands:
        print(" ".join(command))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Kalibr run rejected: {error}") from error
