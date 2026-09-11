#!/usr/bin/env python3
"""Prepare ignored Ubuntu-local SDK, model, and runtime assets without downloads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.assets.import_assets import import_asset
from tools.assets.verify_assets import sha256_path, size_path


def default_sources(home: Path) -> dict[str, Path]:
    """Return legacy source candidates; callers can override every mapping."""
    language = home / "Thirdhand_language"
    return {
        "startouch.sdk": home / "arm/startouch_sdk",
        "xvisio.sdk": home / "xvisio_sdk",
        "funasr.source": language / "FunASR",
        "asr.medium": language / "models/whisper-small",
        "asr.realtime": language / "models/paraformer-streaming",
        "asr.high": language / "models/fun-asr-nano",
        "vision.grounded-sam": (
            home / "th0814/ThirdHand-XVisio/models/huggingface"
        ),
        "runtime.python": language / "runtime/python",
        "runtime.node": language / "runtime/node",
    }


def parse_source(value: str) -> tuple[str, Path]:
    asset_id, separator, source = value.partition("=")
    if not separator or not asset_id or not source:
        raise argparse.ArgumentTypeError("--source must use ASSET_ID=/path")
    return asset_id, Path(source).expanduser()


def prepare_assets(
    root: Path,
    manifest_path: Path,
    sources: dict[str, Path],
) -> dict[str, Any]:
    """Copy only missing local assets and verify existing destinations."""
    root = root.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []

    for asset in manifest.get("assets", []):
        relative = Path(asset["relativePath"])
        if not relative.parts or relative.parts[0] != "local":
            continue
        destination = (root / relative).resolve()
        expected_hash = str(asset.get("sha256", "")).lower()
        expected_size = int(asset.get("sizeBytes", 0))
        result: dict[str, Any] = {
            "id": asset["id"],
            "destination": str(destination),
        }

        if destination.exists():
            actual_hash = sha256_path(destination)
            actual_size = size_path(destination)
            result.update({
                "status": (
                    "already_present"
                    if actual_hash == expected_hash and actual_size == expected_size
                    else "destination_conflict"
                ),
                "actualSha256": actual_hash,
                "actualSizeBytes": actual_size,
            })
        else:
            source = sources.get(asset["id"])
            if source is None or not source.exists():
                result.update({
                    "status": "source_missing",
                    "source": str(source) if source is not None else None,
                })
            elif not expected_hash:
                result.update({
                    "status": "manifest_hash_missing",
                    "source": str(source),
                })
            else:
                result.update(import_asset(
                    source,
                    destination,
                    project_root=root,
                    expected_sha256=expected_hash,
                ))
                result["source"] = str(source)
        results.append(result)

    blocking = [
        result for result in results
        if result["status"] not in {"already_present", "imported"}
        and next(
            asset for asset in manifest["assets"]
            if asset["id"] == result["id"]
        ).get("required", False)
    ]
    return {"ok": not blocking, "assets": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("configs/assets/ubuntu20.manifest.json"),
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        type=parse_source,
        metavar="ASSET_ID=/path",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = args.project_root.resolve()
    manifest = (
        args.manifest
        if args.manifest.is_absolute()
        else root / args.manifest
    )
    sources = default_sources(Path.home())
    sources.update(dict(args.source))
    report = prepare_assets(root, manifest, sources)
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        for asset in report["assets"]:
            print(f"{asset['id']}: {asset['status']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
