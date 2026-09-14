from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "web-control/scripts/read_grasp_robot_pose.py"
SDK = Path("/home/nieqingcao/arm/startouch_sdk")
BRIDGE = Path("/home/nieqingcao/TH-Fanxy/web-control/server")
COMMISSIONED_SOURCE_JOINTS_DEG = (
    -0.163927,
    -2.611904,
    -0.579209,
    33.058620,
    0.338783,
    0.185784,
)


def test_offline_fixture_separates_flange_from_sdk_tool_tcp() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--sdk-path",
            str(SDK),
            "--bridge-root",
            str(BRIDGE),
            "--offline-joints-deg",
            *(str(value) for value in COMMISSIONED_SOURCE_JOINTS_DEG),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(result.stdout)
    assert report["mode"] == "offline_fixture"
    assert report["hardware_access"] == "none"
    assert report["single_arm_constructed"] is False
    assert report["joints"]["signed_sdk_deg"] == pytest.approx(
        COMMISSIONED_SOURCE_JOINTS_DEG
    )
    assert report["sdk_tool_offset"]["xyz_m"] == pytest.approx(
        [0.17334, 0.0, 0.0]
    )
    assert report["base_from_sdk_tool"]["xyz_m"] == pytest.approx(
        [0.2590131849052108, 0.0004346589730736, 0.0411576603511741],
        abs=1e-12,
    )
    assert report["base_from_flange"]["xyz_m"] == pytest.approx(
        [0.1086966343709766, -0.0001602109328228, 0.1274787838684457],
        abs=1e-12,
    )
    assert report["motor_feedback"] is None


def test_help_does_not_require_hardware_or_dependencies() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--sdk-path" in result.stdout
    assert "--bridge-root" in result.stdout
    assert "--offline-joints-deg" in result.stdout
