from __future__ import annotations

import importlib.util
from pathlib import Path
import struct

import pytest


ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "drivers/xvisio/src/xvisio_stream.py"


def load_module():
    assert MODULE.is_file(), "XVisio stream parser is missing"
    spec = importlib.util.spec_from_file_location("xvisio_stream", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_header(module, *, serial: str = "250801DR48FP25002738") -> bytes:
    width, height = 4, 3
    pixels = width * height
    return struct.pack(
        "<8sIIIIQQIIII32s",
        module.MAGIC,
        module.VERSION,
        module.HEADER_SIZE,
        width,
        height,
        1,
        123456789,
        pixels * 3,
        pixels * 4,
        pixels * 3 * 4,
        0,
        serial.encode("ascii").ljust(32, b"\0"),
    )


def test_packet_parser_accepts_valid_bounded_header() -> None:
    module = load_module()
    header = module.parse_header(valid_header(module))
    assert (header.width, header.height) == (4, 3)
    assert header.serial == "250801DR48FP25002738"


def test_packet_parser_rejects_wrong_magic() -> None:
    module = load_module()
    packet = bytearray(valid_header(module))
    packet[:8] = b"BADHDR00"
    with pytest.raises(module.StreamProtocolError):
        module.parse_header(bytes(packet))


def test_packet_parser_rejects_unbounded_dimensions() -> None:
    module = load_module()
    packet = bytearray(valid_header(module))
    struct.pack_into("<II", packet, 16, 50000, 50000)
    with pytest.raises(module.StreamProtocolError):
        module.parse_header(bytes(packet))


def test_stream_error_preserves_protocol_failure_when_sdk_stderr_exists() -> None:
    module = load_module()
    stream = module.XVisioStream(MODULE, expected_serial="250801DR48FP25002738")
    stream._error = module.StreamProtocolError(
        "sequence and timestamp must strictly increase"
    )
    stream._stderr_tail.extend(
        b"[LOG ERROR] cannot switch from manual to automatic argument indexing"
    )

    with pytest.raises(RuntimeError) as captured:
        stream.read_after(0, timeout_s=0.0)

    message = str(captured.value)
    assert "sequence and timestamp must strictly increase" in message
    assert "cannot switch from manual to automatic argument indexing" in message
