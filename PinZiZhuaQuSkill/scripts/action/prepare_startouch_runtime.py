#!/usr/bin/env python3
"""Prepare the project-contained Startouch safety runtime without hardware."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from native.startouch.vendor_runtime import (  # noqa: E402
    prepare_startouch_runtime,
    validate_startouch_runtime,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-sdk",
        type=Path,
        default=Path("/home/nieqingcao/arm/startouch_sdk"),
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=PROJECT_ROOT / "build/startouch_runtime/startouch_sdk",
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=PROJECT_ROOT / "native/startouch/startouch_source.json",
    )
    args = parser.parse_args(argv)
    destination = args.destination.expanduser().resolve()
    if PROJECT_ROOT not in destination.parents:
        raise SystemExit("destination_must_stay_inside_project")
    runtime_manifest = prepare_startouch_runtime(
        args.source_sdk.expanduser().resolve(),
        destination,
        args.source_manifest.expanduser().resolve(),
    )
    validation = validate_startouch_runtime(
        destination, args.source_manifest.expanduser().resolve()
    )
    print(json.dumps({
        "config_sha256": validation.config_sha256,
        "hardware_access_performed": False,
        "ok": True,
        "profile_id": validation.profile_id,
        "reproducible_build_verified": validation.reproducible_build_verified,
        "runtime_manifest": str(runtime_manifest),
        "runtime_manifest_id": (
            "sha256:" + validation.runtime_manifest_sha256
        ),
        "runtime_root": str(validation.root),
        "sdk_version": validation.sdk_version,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
