"""Packaging contract tests for the PEP 517 build backend."""

from __future__ import annotations

import importlib
import re
from pathlib import Path


def test_declared_build_backend_is_importable() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    match = re.search(
        r'^build-backend\s*=\s*"(?P<backend>[^"]+)"',
        pyproject.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )

    assert match is not None, "pyproject.toml must declare build-backend"
    module_name, _, object_path = match.group("backend").partition(":")
    backend: object = importlib.import_module(module_name)
    for attribute in filter(None, object_path.split(".")):
        backend = getattr(backend, attribute)

    assert callable(getattr(backend, "build_wheel", None))
