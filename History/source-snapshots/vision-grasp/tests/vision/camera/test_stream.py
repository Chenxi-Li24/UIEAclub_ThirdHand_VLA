import os
from pathlib import Path
import stat
import textwrap
import time

from thirdhand_va.vision.camera.protocol import encode_packet
from thirdhand_va.vision.camera.stream import XVisioStream
from thirdhand_va.common.contracts import RgbdFrame

import numpy as np
import pytest


def make_frame(sequence: int) -> RgbdFrame:
    depth = np.full((1, 2), 0.4, dtype=np.float32)
    xyz = np.zeros((1, 2, 3), dtype=np.float32)
    xyz[..., 2] = depth
    return RgbdFrame(
        sequence=sequence,
        monotonic_ns=sequence * 100,
        camera_serial="250801DR48FP25002738",
        rgb=np.zeros((1, 2, 3), dtype=np.uint8),
        depth_m=depth,
        xyz_camera_m=xyz,
    )


def test_stream_retains_only_latest_frame(tmp_path: Path) -> None:
    first = tmp_path / "first.packet"
    second = tmp_path / "second.packet"
    first.write_bytes(encode_packet(make_frame(1)))
    second.write_bytes(encode_packet(make_frame(2)))
    executable = tmp_path / "fake_xvisio_stream.py"
    executable.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import os
            import sys
            import time
            fd = int(sys.argv[1])
            for packet_path in {([str(first), str(second)])!r}:
                with open(packet_path, "rb") as stream:
                    os.write(fd, stream.read())
            time.sleep(1.0)
            """
        ),
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    with XVisioStream(
        executable,
        expected_serial="250801DR48FP25002738",
    ) as stream:
        deadline = time.monotonic() + 0.5
        frame = None
        while time.monotonic() < deadline:
            frame = stream.read_after(0, timeout_s=0.05)
            if frame is not None and frame.sequence == 2:
                break

    assert frame is not None
    assert frame.sequence == 2


def test_stream_timeout_returns_none(tmp_path: Path) -> None:
    executable = tmp_path / "idle_xvisio_stream.py"
    executable.write_text(
        "#!/usr/bin/env python3\nimport time\ntime.sleep(1.0)\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    with XVisioStream(
        executable,
        expected_serial="250801DR48FP25002738",
    ) as stream:
        assert stream.read_after(0, timeout_s=0.01) is None


def test_stream_timeout_diagnostics_include_live_native_stderr(tmp_path: Path) -> None:
    executable = tmp_path / "opening_xvisio_stream.py"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "print('xvisio: opening device', file=sys.stderr, flush=True)\n"
        "time.sleep(1.0)\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    with XVisioStream(
        executable,
        expected_serial="250801DR48FP25002738",
    ) as stream:
        assert stream.read_after(0, timeout_s=0.05) is None
        diagnostic = stream.diagnostics()

    assert diagnostic["process_running"] is True
    assert diagnostic["exit_code"] is None
    assert diagnostic["native_stderr_tail"] == "xvisio: opening device"


def test_stream_reports_native_stderr_when_camera_is_missing(tmp_path: Path) -> None:
    """Suppressing native stderr must reduce this to an unhelpful EOF error."""
    executable = tmp_path / "failed_xvisio_stream.py"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('xvisio: no device found', file=sys.stderr)\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    with XVisioStream(
        executable,
        expected_serial="250801DR48FP25002738",
    ) as stream:
        with pytest.raises(RuntimeError, match="xvisio: no device found"):
            stream.read_after(0, timeout_s=1.0)
