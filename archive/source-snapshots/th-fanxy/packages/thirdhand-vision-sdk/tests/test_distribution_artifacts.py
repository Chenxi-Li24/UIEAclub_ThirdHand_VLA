from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
from typing import Iterator
import zipfile

from setuptools import build_meta


ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 1024 * 1024


@contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def build_distributions(root: Path, output: Path) -> dict[str, Path]:
    source = output / "source"
    shutil.copytree(
        root,
        source,
        ignore=shutil.ignore_patterns("build", "dist", "*.egg-info", "__pycache__"),
    )
    artifacts = output / "artifacts"
    artifacts.mkdir()
    with working_directory(source):
        wheel = build_meta.build_wheel(str(artifacts))
        sdist = build_meta.build_sdist(str(artifacts))
    return {"wheel": artifacts / wheel, "sdist": artifacts / sdist}


def read_distribution(path: Path) -> dict[str, bytes]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}
    with tarfile.open(path, mode="r:gz") as archive:
        payloads: dict[str, bytes] = {}
        for member in archive.getmembers():
            assert not member.issym() and not member.islnk()
            if member.isfile():
                stream = archive.extractfile(member)
                assert stream is not None
                payloads[member.name] = stream.read()
        return payloads


def test_wheel_and_sdist_include_research_metadata_without_runtime_assets(
    tmp_path: Path,
) -> None:
    artifacts = build_distributions(ROOT, tmp_path)
    forbidden_suffixes = {".bag", ".engine", ".key", ".log", ".npz", ".onnx", ".pem", ".pt", ".pth"}
    forbidden_tokens = (
        ("/" + "home" + "/").encode(),
        ("pyreal" + "sense2").encode(),
        ("Authorization: " + "Bearer ").encode(),
    )

    for path in artifacts.values():
        payloads = read_distribution(path)
        names = tuple(payloads)
        assert any(name.endswith("LICENSE") for name in names)
        assert any(name.endswith("LICENSES.md") for name in names)
        assert any(name.endswith("SOURCE_MAP.json") for name in names)
        assert any(name.endswith("configs/default.yaml") for name in names)
        assert any(name.endswith("thirdhand_vision/py.typed") for name in names)
        assert any(name.endswith("thirdhand_vision/core/types.py") for name in names)
        for name, payload in payloads.items():
            relative = PurePosixPath(name)
            assert relative.suffix.lower() not in forbidden_suffixes
            assert len(payload) <= MAX_FILE_BYTES
            assert all(token not in payload for token in forbidden_tokens)
