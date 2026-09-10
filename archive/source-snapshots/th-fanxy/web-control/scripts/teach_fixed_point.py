#!/usr/bin/env python3
"""Read J1-J6 through the existing bridge and save one fixed waypoint safely."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import logging
import os
from pathlib import Path
import shutil
import tempfile

import yaml

from fixed_pick_place import (
    BridgeClient,
    ConfigurationError,
    POINT_NAMES,
    configure_logging,
    load_config,
    validate_waypoint,
)


def save_point(
    config_path: Path,
    point: str,
    joints_deg: list[float],
) -> Path:
    config = load_config(config_path, require_all_points=False)
    validated = validate_waypoint(point, joints_deg, config["joint_limits_deg"])
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    updated = deepcopy(raw)
    updated.setdefault("waypoints", {})[point] = [round(value, 6) for value in validated]

    backup_dir = config_path.parent / ".fixed_pick_place_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / (
        f"{config_path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.yaml"
    )
    shutil.copy2(config_path, backup)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{config_path.name}.",
        suffix=".tmp",
        dir=config_path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(updated, stream, sort_keys=False, allow_unicode=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, config_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return backup


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("point", choices=POINT_NAMES)
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "configs" / "tasks" / "fixed_pick_place.yaml",
    )
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="read and validate the point without writing the configuration",
    )
    args = parser.parse_args()

    logger, log_path = configure_logging(root)
    mode = "simulate" if args.simulate else "real"
    bridge = BridgeClient(
        root / "web-control" / "server" / "startouch_bridge.py",
        mode,
        logger,
    )
    failed = True
    try:
        config = load_config(args.config, require_all_points=False)
        bridge.start()
        joints = bridge.connect()
        validated = validate_waypoint(args.point, joints, config["joint_limits_deg"])
        logger.info(
            "point=%s current_joints_deg=%s",
            args.point,
            ", ".join(f"{value:.6f}" for value in validated),
        )
        if not args.print_only:
            backup = save_point(args.config, args.point, validated)
            logger.info("saved %s; previous file backed up to %s", args.config, backup)
        failed = False
        return 0
    except (ConfigurationError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1
    finally:
        bridge.close(failed=failed)
        logger.info("final log: %s", log_path)


if __name__ == "__main__":
    raise SystemExit(main())
