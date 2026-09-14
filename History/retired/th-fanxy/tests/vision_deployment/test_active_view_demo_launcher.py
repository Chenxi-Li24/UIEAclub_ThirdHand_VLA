from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
LAUNCHER = ROOT / "scripts" / "vision" / "start_active_view_demo.sh"


def fake_python_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture = tmp_path / "python-args.txt"
    python = fake_bin / "python3"
    python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    environment = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "CAPTURE": str(capture),
    }
    return environment, capture


def test_launcher_executes_loopback_static_server(tmp_path: Path) -> None:
    environment, capture = fake_python_environment(tmp_path)

    result = subprocess.run(
        ["bash", str(LAUNCHER), "--port", "43130"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "-m",
        "http.server",
        "43130",
        "--bind",
        "127.0.0.1",
        "--directory",
        str(ROOT / "web-control" / "web"),
    ]
    assert "http://127.0.0.1:43130/camera-test.html?demo=1" in result.stdout
    assert "不会连接相机、机械臂或夹爪" in result.stdout


def test_launcher_rejects_invalid_ports_before_starting_python(tmp_path: Path) -> None:
    environment, capture = fake_python_environment(tmp_path)

    for invalid_port in ("abc", "0", "1023", "65536"):
        result = subprocess.run(
            ["bash", str(LAUNCHER), "--port", invalid_port],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 2
        assert "端口必须是 1024 到 65535" in result.stderr

    assert not capture.exists()


def test_launcher_uses_default_port_without_external_environment(tmp_path: Path) -> None:
    environment, capture = fake_python_environment(tmp_path)
    environment.pop("ACTIVE_VIEW_DEMO_PORT", None)
    environment.pop("PORT", None)

    result = subprocess.run(
        ["bash", str(LAUNCHER)],
        cwd=ROOT,
        env={**os.environ, **environment},
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0
    assert capture.read_text(encoding="utf-8").splitlines()[2] == "43130"
    assert "http://127.0.0.1:43130/camera-test.html?demo=1" in result.stdout
