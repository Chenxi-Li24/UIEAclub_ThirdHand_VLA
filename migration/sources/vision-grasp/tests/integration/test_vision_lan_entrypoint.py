from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from apps.vision_lan.main import build_parser, run, validate_args


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RecordingService:
    def __init__(self) -> None:
        self.start_count = 0
        self.stop_count = 0

    def start(self) -> None:
        self.start_count += 1

    def stop(self) -> None:
        self.stop_count += 1


class RecordingServer:
    def __init__(self, address: tuple[str, int]) -> None:
        self.address = address
        self.start_count = 0
        self.stop_count = 0

    def start(self) -> tuple[str, int]:
        self.start_count += 1
        return self.address

    def stop(self) -> None:
        self.stop_count += 1


def test_lan_entrypoint_defaults_are_read_only_and_use_new_port() -> None:
    parser = build_parser()
    args = validate_args(parser.parse_args([
        "--host",
        "192.168.58.68",
        "--allowed-network",
        "192.168.58.0/24",
    ]))

    assert args.port == 8770
    assert args.algorithm_url == "http://127.0.0.1:3000/camera_lumos_vision"
    assert args.depth_url == "http://127.0.0.1:3000/camera_xvisio_depth"
    assert not any(
        "robot" in action.dest or "control" in action.dest
        for action in parser._actions
    )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            ["--host", "0.0.0.0", "--allowed-network", "192.168.58.0/24"],
            "specific LAN",
        ),
        (
            ["--host", "127.0.0.1", "--allowed-network", "127.0.0.0/8"],
            "specific LAN",
        ),
        (
            ["--host", "192.168.59.68", "--allowed-network", "192.168.58.0/24"],
            "inside --allowed-network",
        ),
        (
            [
                "--host",
                "192.168.58.68",
                "--allowed-network",
                "192.168.58.0/24",
                "--algorithm-url",
                "http://192.168.58.10:3000/camera_lumos_vision",
            ],
            "loopback HTTP",
        ),
    ],
)
def test_lan_entrypoint_rejects_unsafe_network_arguments(
    arguments: list[str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_args(build_parser().parse_args(arguments))


def test_lan_entrypoint_generates_token_and_closes_owned_resources(
    capsys,
) -> None:
    service = RecordingService()
    server = RecordingServer(("192.168.58.68", 8770))
    stop = threading.Event()
    stop.set()
    args = validate_args(build_parser().parse_args([
        "--host",
        "192.168.58.68",
        "--allowed-network",
        "192.168.58.0/24",
    ]))

    exit_code = run(
        args,
        stop,
        service_factory=lambda *_args, **_kwargs: service,
        server_factory=lambda *_args, **_kwargs: server,
    )

    event = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert event["type"] == "vision_lan_ready"
    assert event["stream_url"].startswith(
        "http://192.168.58.68:8770/stream.mjpg?token="
    )
    assert event["health_url"].startswith(
        "http://192.168.58.68:8770/health?token="
    )
    assert service.start_count == service.stop_count == 1
    assert server.start_count == server.stop_count == 1
    assert event["read_only"] is True
    assert event["robot_control_enabled"] is False


def test_vscode_debug_entry_starts_the_lan_viewer_on_8770() -> None:
    launch = json.loads((PROJECT_ROOT / ".vscode/launch.json").read_text())
    configuration = next(
        item
        for item in launch["configurations"]
        if item.get("name") == "Vision LAN: Debug Windows Viewer"
    )

    assert configuration["type"] == "debugpy"
    assert configuration["module"] == "apps.vision_lan.main"
    assert configuration["args"] == [
        "--host",
        "192.168.58.68",
        "--allowed-network",
        "192.168.58.0/24",
        "--port",
        "8770",
    ]
