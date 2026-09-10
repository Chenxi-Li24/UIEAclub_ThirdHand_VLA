#!/usr/bin/env python3
"""Verify local delivery assets without downloading or modifying them."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from typing import Any


def sha256_path(path: Path) -> str:
    """Hash a file or a directory tree using stable relative paths."""
    digest = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with child.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def size_path(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _platform_compatible(requirements: dict[str, Any]) -> bool:
    architectures = requirements.get("architectures", [])
    systems = requirements.get("systems", [])
    return (not architectures or platform.machine() in architectures) and (
        not systems or platform.system().lower() in {value.lower() for value in systems}
    )


def verify_manifest(project_root: Path, manifest_path: Path) -> dict[str, Any]:
    """Return an asset report and never modify or download payloads."""
    root = project_root.resolve()
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    reports: list[dict[str, Any]] = []

    for asset in document.get("assets", []):
        relative = Path(asset["relativePath"])
        candidate = (root / relative).resolve()
        if relative.is_absolute() or not _inside(root, candidate):
            raise ValueError(f"asset path resolves outside project root: {relative}")

        report: dict[str, Any] = {
            "id": asset["id"],
            "kind": asset["kind"],
            "required": bool(asset.get("required", False)),
            "relativePath": relative.as_posix(),
        }
        if not candidate.exists():
            report["status"] = "missing"
        else:
            actual_size = size_path(candidate)
            actual_hash = sha256_path(candidate)
            report.update({"actualSizeBytes": actual_size, "actualSha256": actual_hash})
            if actual_size != asset.get("sizeBytes"):
                report["status"] = "size_mismatch"
            elif actual_hash.lower() != str(asset.get("sha256", "")).lower():
                report["status"] = "hash_mismatch"
            elif asset.get("licenseStatus") not in {"recorded", "redistributable", "local-only"}:
                report["status"] = "license_unrecorded"
            elif not _platform_compatible(asset.get("compatibility", {})):
                report["status"] = "incompatible_platform"
            else:
                report["status"] = "ready"
        reports.append(report)

    blocking = [item for item in reports if item["required"] and item["status"] != "ready"]
    return {
        "ok": not blocking,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "assets": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = verify_manifest(args.project_root, args.manifest)
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        for asset in report["assets"]:
            print(f"{asset['id']}: {asset['status']} ({asset['relativePath']})")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
