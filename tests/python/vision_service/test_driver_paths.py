from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "drivers/xvisio/src/xvisio_stream.py"


def load_module():
    assert MODULE.is_file(), "XVisio stream module is missing"
    spec = importlib.util.spec_from_file_location("xvisio_stream_paths", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_executable_is_project_local() -> None:
    module = load_module()
    assert module.default_executable(ROOT) == (
        ROOT / "runtime/build/xvisio/xvisio_rgbd_stream"
    )


def test_driver_source_and_build_script_are_project_local() -> None:
    assert (ROOT / "drivers/xvisio/native/CMakeLists.txt").is_file()
    assert (ROOT / "drivers/xvisio/native/xvisio_rgbd_stream.cpp").is_file()
    assert (ROOT / "drivers/xvisio/scripts/build.sh").is_file()
