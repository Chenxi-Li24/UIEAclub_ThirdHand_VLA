from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts.build_release import (
    ReleaseValidationError,
    build_release,
    release_candidates,
    validate_release_contents,
)


ROOT = Path(__file__).resolve().parents[1]


def test_release_candidates_use_a_strict_allowlist() -> None:
    candidates = release_candidates(ROOT)
    relative = {path.relative_to(ROOT).as_posix() for path in candidates}

    assert "LICENSE" in relative
    assert "README.md" in relative
    assert "src/thirdhand_vision/__init__.py" in relative
    assert "docs/superpowers/plans/2026-08-06-offline-vision-sdk.md" not in relative
    assert not any("__pycache__" in path.parts for path in candidates)
    assert not any(path.name == ".git" for path in candidates)


def test_package_carries_mit_license() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notices = (ROOT / "LICENSES.md").read_text(encoding="utf-8")

    assert "Permission is hereby granted, free of charge" in license_text
    assert "MIT" in notices


@pytest.mark.parametrize(
    "relative_path",
    [
        "weights/model.pt",
        "weights/model.pth",
        "weights/model.onnx",
        "weights/model.engine",
        "captures/frame.npz",
        "captures/session.bag",
        "runtime/server.log",
        "runtime/service.pid",
        "secrets/auth.key",
        "secrets/cert.pem",
    ],
)
def test_release_validation_rejects_sensitive_binary_suffixes(
    tmp_path: Path,
    relative_path: str,
) -> None:
    candidate = tmp_path / relative_path
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"not-for-release")

    with pytest.raises(ReleaseValidationError, match="forbidden suffix"):
        validate_release_contents(tmp_path, [candidate])


def test_release_validation_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("safe", encoding="utf-8")
    link = tmp_path / "linked.md"
    link.symlink_to(target)

    with pytest.raises(ReleaseValidationError, match="symlink"):
        validate_release_contents(tmp_path, [link])


@pytest.mark.parametrize(
    "content",
    [
        "import " + "pyreal" + "sense2",
        "from " + "startouch" + " import bus",
        "Authorization: " + "Bearer" + " abcdefghijklmnopqrstuvwxyz",
        "-----BEGIN " + "PRIVATE KEY-----",
    ],
)
def test_release_validation_rejects_hardware_or_secret_text(
    tmp_path: Path,
    content: str,
) -> None:
    candidate = tmp_path / "module.py"
    candidate.write_text(content, encoding="utf-8")

    with pytest.raises(ReleaseValidationError, match="forbidden content"):
        validate_release_contents(tmp_path, [candidate])


def test_release_validation_rejects_absolute_config_paths(tmp_path: Path) -> None:
    candidate = tmp_path / "configs" / "unsafe.yaml"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("checkpoint: /srv/private/model.pth\n", encoding="utf-8")

    with pytest.raises(ReleaseValidationError, match="absolute path"):
        validate_release_contents(tmp_path, [candidate])


def test_build_release_is_deterministic_and_manifested(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    build_release(ROOT, first)
    build_release(ROOT, second)

    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "thirdhand-vision-sdk/LICENSE" in names
        assert "thirdhand-vision-sdk/MANIFEST.sha256" in names
        assert all(info.date_time == (2026, 8, 6, 0, 0, 0) for info in archive.infolist())
        assert not any("docs/superpowers" in name for name in names)
