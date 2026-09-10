#!/usr/bin/env python3
"""Build a deterministic, filtered ThirdHand Vision SDK release archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml


ARCHIVE_ROOT = "thirdhand-vision-sdk"
FIXED_ZIP_TIME = (2026, 8, 6, 0, 0, 0)
MANIFEST_NAME = "MANIFEST.sha256"

ALLOWED_ROOT_FILES = frozenset(
    {
        "LICENSE",
        "LICENSES.md",
        MANIFEST_NAME,
        "README.md",
        "SOURCE_MAP.json",
        "pyproject.toml",
    }
)
REQUIRED_ROOT_FILES = ALLOWED_ROOT_FILES - {MANIFEST_NAME}
ALLOWED_TREES = frozenset({"configs", "docs", "examples", "scripts", "src", "tests"})
EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
    }
)
FORBIDDEN_SUFFIXES = frozenset(
    {".bag", ".engine", ".key", ".log", ".npz", ".onnx", ".pem", ".pid", ".pt", ".pth"}
)
TEXT_SUFFIXES = frozenset(
    {".cfg", ".ini", ".json", ".md", ".py", ".rst", ".toml", ".txt", ".yaml", ".yml"}
)
CONFIG_SUFFIXES = frozenset({".json", ".yaml", ".yml"})

# Strings are composed so this guard does not flag its own source file.
FORBIDDEN_TEXT_RULES = (
    (
        "hardware runtime import",
        re.compile(r"\b(?:import|from)\s+" + "pyreal" + "sense2" + r"\b", re.IGNORECASE),
    ),
    (
        "robot/CAN runtime import",
        re.compile(
            r"\b(?:import|from)\s+(?:" + "start" + "ouch|can)" + r"(?:\b|\.)",
            re.IGNORECASE,
        ),
    ),
    (
        "bearer credential",
        re.compile(r"\b" + "bear" + "er" + r"\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    ),
    (
        "private key",
        re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?" + "PRIVATE KEY-----", re.IGNORECASE),
    ),
)


class ReleaseValidationError(ValueError):
    """Raised when a release candidate violates packaging policy."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_excluded(relative: Path) -> bool:
    if relative.parts[:2] == ("docs", "superpowers"):
        return True
    return any(
        part in EXCLUDED_PARTS
        or part.endswith(".egg-info")
        or (part.startswith(".") and part not in {".", ".."})
        for part in relative.parts
    )


def release_candidates(root: Path) -> list[Path]:
    """Return sorted files from the explicit teammate-release allowlist."""

    root = Path(root)
    candidates: list[Path] = []
    for name in sorted(ALLOWED_ROOT_FILES):
        path = root / name
        if path.exists() or path.is_symlink():
            candidates.append(path)

    for tree_name in sorted(ALLOWED_TREES):
        tree = root / tree_name
        if not tree.exists():
            continue
        for path in tree.rglob("*"):
            relative = path.relative_to(root)
            if _is_excluded(relative):
                continue
            if path.is_file() or path.is_symlink():
                candidates.append(path)

    return sorted(candidates, key=lambda path: path.relative_to(root).as_posix())


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def _is_absolute_config_value(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith(("/", "\\\\")) or bool(
        re.match(r"^[A-Za-z]:[\\/]", stripped)
    )


def _validate_config_paths(path: Path, relative: Path, text: str) -> None:
    if relative.parts[0] != "configs" or path.suffix.lower() not in CONFIG_SUFFIXES:
        return
    try:
        parsed = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ReleaseValidationError(f"invalid config {relative.as_posix()}: {exc}") from exc
    absolute = next((value for value in _walk_strings(parsed) if _is_absolute_config_value(value)), None)
    if absolute is not None:
        raise ReleaseValidationError(
            f"absolute path in config {relative.as_posix()}: {absolute!r}"
        )


def validate_release_contents(root: Path, paths: Iterable[Path]) -> None:
    """Reject paths, file types, imports and credentials unsafe for release."""

    root = Path(root).absolute()
    seen: set[str] = set()
    for candidate in paths:
        path = Path(candidate).absolute()
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise ReleaseValidationError(f"candidate outside release root: {path}") from exc
        relative_text = relative.as_posix()
        if relative_text in seen:
            raise ReleaseValidationError(f"duplicate release candidate: {relative_text}")
        seen.add(relative_text)

        if path.is_symlink():
            raise ReleaseValidationError(f"symlink is not allowed: {relative_text}")
        if not path.is_file():
            raise ReleaseValidationError(f"candidate is not a regular file: {relative_text}")
        if _is_excluded(relative):
            raise ReleaseValidationError(f"excluded path in release: {relative_text}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ReleaseValidationError(f"forbidden suffix in release: {relative_text}")

        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ReleaseValidationError(f"non-UTF-8 text file: {relative_text}") from exc
        for label, pattern in FORBIDDEN_TEXT_RULES:
            if pattern.search(text):
                raise ReleaseValidationError(
                    f"forbidden content ({label}) in release: {relative_text}"
                )
        _validate_config_paths(path, relative, text)


def _write_atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _manifest_content(root: Path, paths: Iterable[Path]) -> str:
    rows = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST_NAME:
            continue
        rows.append(f"{_sha256(path)}  {relative}")
    return "\n".join(sorted(rows, key=lambda row: row.split("  ", 1)[1])) + "\n"


def _zip_info(archive_name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(archive_name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def build_release(root: Path, output: Path) -> str:
    """Validate and build the release, returning the archive SHA-256."""

    root = Path(root).resolve()
    output = Path(output).absolute()
    missing = sorted(name for name in REQUIRED_ROOT_FILES if not (root / name).is_file())
    if missing:
        raise ReleaseValidationError(f"missing required release files: {', '.join(missing)}")

    initial = release_candidates(root)
    validate_release_contents(root, initial)
    _write_atomic_text(root / MANIFEST_NAME, _manifest_content(root, initial))

    candidates = release_candidates(root)
    validate_release_contents(root, candidates)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, mode="w") as archive:
            for path in candidates:
                relative = path.relative_to(root).as_posix()
                archive_name = f"{ARCHIVE_ROOT}/{relative}"
                archive.writestr(_zip_info(archive_name), path.read_bytes())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()

    archive_hash = _sha256(output)
    _write_atomic_text(
        Path(f"{output}.sha256"),
        f"{archive_hash}  {output.name}\n",
    )
    return archive_hash


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="destination ZIP path")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="SDK repository root (defaults to the script's parent repository)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    checksum = build_release(args.root, args.output)
    print(f"built {args.output}")
    print(f"sha256 {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
