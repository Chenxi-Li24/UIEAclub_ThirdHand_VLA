#!/usr/bin/env python3
"""Build the Startouch extension for the project Python without modifying the SDK source."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def target_python_info(python: Path) -> dict[str, str]:
    code = (
        "import json,sysconfig;"
        "print(json.dumps({"
        "'include':sysconfig.get_path('include'),"
        "'libdir':sysconfig.get_config_var('LIBDIR'),"
        "'library':sysconfig.get_config_var('LDLIBRARY'),"
        "'ext_suffix':sysconfig.get_config_var('EXT_SUFFIX')"
        "}))"
    )
    result = subprocess.run(
        [str(python), "-c", code],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def detect_pybind11_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        candidate = explicit.resolve()
    else:
        result = subprocess.run(
            [sys.executable, "-c", "import pybind11; print(pybind11.get_cmake_dir())"],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "pybind11 >= 2.10 is required by the build interpreter; "
                "install it or pass --pybind11-dir"
            )
        candidate = Path(result.stdout.strip()).resolve()
    if not (candidate / "pybind11Config.cmake").is_file():
        raise FileNotFoundError(f"invalid pybind11 CMake directory: {candidate}")
    return candidate


def ignore_sdk_artifacts(_directory: str, names: list[str]) -> set[str]:
    ignored = {
        name
        for name in names
        if name == "build" or name.startswith("build-py")
    }
    ignored.update({".git", "__pycache__", ".pytest_cache"} & set(names))
    ignored.update(
        name
        for name in names
        if name.startswith("startouch.cpython-") and name.endswith(".so")
    )
    return ignored


def stage_runtime(source: Path, extension: Path, staged: Path) -> Path:
    sdk_root = staged / "startouch_sdk"
    interface_dir = sdk_root / "interface_py"
    interface_dir.mkdir(parents=True)

    staged_extension = interface_dir / extension.name
    shutil.copy2(extension, staged_extension)
    shutil.copy2(source / "interface_py/startouchclass.py", interface_dir)
    shutil.copy2(source / "src/libstartouch.so", interface_dir)
    shutil.copytree(source / "src/config", sdk_root / "src/config")
    shutil.copytree(
        source / "src/param_csv_gripper",
        sdk_root / "param_csv_gripper",
    )
    return staged_extension


def build(
    project_root: Path,
    sdk_path: Path,
    target_python: Path,
    destination: Path,
    pybind11_dir: Path,
) -> dict[str, str]:
    root = project_root.resolve()
    sdk = sdk_path.resolve()
    python = target_python.resolve()
    output = destination.resolve()
    output.relative_to((root / "local").resolve())
    if not (sdk / "CMakeLists.txt").is_file():
        raise FileNotFoundError(f"Startouch SDK source is incomplete: {sdk}")
    if not python.is_file():
        raise FileNotFoundError(f"target Python is missing: {python}")

    info = target_python_info(python)
    python_library = Path(info["libdir"]) / info["library"]
    with tempfile.TemporaryDirectory(prefix="thirdhand-startouch-build-") as temp:
        temporary = Path(temp)
        source = temporary / "source"
        build_dir = temporary / "build"
        shutil.copytree(sdk, source, ignore=ignore_sdk_artifacts)
        run([
            "cmake",
            "-S", str(source),
            "-B", str(build_dir),
            f"-Dpybind11_DIR={pybind11_dir}",
            f"-DPYTHON_EXECUTABLE={python}",
            f"-DPYTHON_LIBRARY={python_library}",
            f"-DPYTHON_INCLUDE_DIR={info['include']}",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_BUILD_WITH_INSTALL_RPATH=TRUE",
            "-DCMAKE_INSTALL_RPATH=$ORIGIN",
        ])
        run(["cmake", "--build", str(build_dir), "--parallel", "2"])

        extension = source / "interface_py" / f"startouch{info['ext_suffix']}"
        required = [
            extension,
            source / "interface_py" / "startouchclass.py",
            source / "src" / "libstartouch.so",
            source / "src/config/robot_kinematics.yaml",
            source / "src/config/FastTouchV2.SLDASM.urdf",
            source / "src/param_csv_gripper",
        ]
        missing = [str(item) for item in required if not item.exists()]
        if missing:
            raise FileNotFoundError(f"build output is incomplete: {missing}")

        staged = temporary / "runtime"
        staged_extension = stage_runtime(source, extension, staged)

        smoke_env = {
            **os.environ,
            "PYTHONPATH": str(staged_extension.parent),
        }
        subprocess.run(
            [
                str(python),
                "-c",
                "import startouch; from startouchclass import SingleArm; "
                "arm=SingleArm(can_interface_='can0', gripper=True, dry_run=True); "
                "del arm; "
                "print(startouch.__file__, SingleArm.__name__)",
            ],
            check=True,
            env=smoke_env,
            cwd=staged / "startouch_sdk" / "src",
        )

        if output.exists():
            shutil.rmtree(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged, output)

    return {
        "status": "ready",
        "python": str(python),
        "modulePath": str(output / "startouch_sdk/interface_py"),
        "extension": str(output / staged_extension.relative_to(staged)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--sdk", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--pybind11-dir", type=Path)
    args = parser.parse_args()

    root = args.project_root.resolve()
    result = build(
        root,
        args.sdk or root / "local/sdk/startouch",
        args.python or root / "local/runtimes/python/bin/python",
        args.destination or root / "local/generated/startouch-python",
        detect_pybind11_dir(args.pybind11_dir),
    )
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
