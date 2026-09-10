"""Bounded owner for the local XVisio native RGB-D/XYZ stream."""

from __future__ import annotations

from pathlib import Path
import socket
import subprocess
import threading
from typing import BinaryIO

from thirdhand_va.common.contracts import RgbdFrame

from .protocol import read_one_packet


class XVisioStream:
    """Own one native process and expose only its newest validated frame."""

    def __init__(self, executable: str | Path, *, expected_serial: str) -> None:
        self.executable = Path(executable).resolve()
        self.expected_serial = expected_serial
        self._condition = threading.Condition()
        self._latest: RgbdFrame | None = None
        self._error: BaseException | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._socket: socket.socket | None = None
        self._reader: BinaryIO | None = None
        self._thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lock = threading.Lock()
        self._stderr_tail = bytearray()

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("XVisio stream is already started")
        if not self.executable.is_file():
            raise RuntimeError(f"XVisio stream executable not found: {self.executable}")
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self._process = subprocess.Popen(
                [str(self.executable), str(child.fileno())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                pass_fds=(child.fileno(),),
            )
        finally:
            child.close()
        self._socket = parent
        self._reader = parent.makefile("rb", buffering=0)
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name="xvisio-stderr-reader",
            daemon=True,
        )
        self._stderr_thread.start()
        self._thread = threading.Thread(
            target=self._read_loop,
            name="xvisio-rgbd-reader",
            daemon=True,
        )
        self._thread.start()

    def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            chunk = process.stderr.read1(4096)
            if not chunk:
                return
            with self._stderr_lock:
                self._stderr_tail.extend(chunk)
                if len(self._stderr_tail) > 65_536:
                    del self._stderr_tail[:-65_536]

    def _native_stderr_text(self) -> str:
        with self._stderr_lock:
            value = bytes(self._stderr_tail)
        return value.decode("utf-8", errors="replace").strip()

    def diagnostics(self) -> dict[str, object]:
        """Return a non-blocking snapshot suitable for timeout reports."""

        process = self._process
        exit_code = None if process is None else process.poll()
        detail = self._native_stderr_text()
        return {
            "executable": str(self.executable),
            "process_started": process is not None,
            "process_running": process is not None and exit_code is None,
            "exit_code": exit_code,
            "native_stderr_tail": detail or None,
        }

    def _read_loop(self) -> None:
        assert self._reader is not None
        previous_sequence = 0
        previous_stamp = 0
        try:
            while True:
                frame = read_one_packet(
                    self._reader,
                    expected_serial=self.expected_serial,
                )
                if (
                    frame.sequence <= previous_sequence
                    or frame.monotonic_ns <= previous_stamp
                ):
                    raise RuntimeError(
                        "XVisio sequence and timestamp must strictly increase"
                    )
                previous_sequence = frame.sequence
                previous_stamp = frame.monotonic_ns
                with self._condition:
                    self._latest = frame
                    self._condition.notify_all()
        except BaseException as error:
            process = self._process
            if process is not None:
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
                if process.poll() is not None:
                    if self._stderr_thread is not None:
                        self._stderr_thread.join(timeout=0.5)
                    detail = self._native_stderr_text()
                    if detail:
                        error = RuntimeError(detail)
            with self._condition:
                self._error = error
                self._condition.notify_all()

    def read_after(self, sequence: int, timeout_s: float) -> RgbdFrame | None:
        with self._condition:
            if self._latest is None or self._latest.sequence <= sequence:
                self._condition.wait_for(
                    lambda: self._error is not None
                    or (
                        self._latest is not None
                        and self._latest.sequence > sequence
                    ),
                    timeout=max(0.0, float(timeout_s)),
                )
            if self._latest is not None and self._latest.sequence > sequence:
                return self._latest
            if self._error is not None:
                raise RuntimeError(f"XVisio native stream failed: {self._error}")
            return None

    def close(self) -> None:
        process, stream, reader, thread, stderr_thread = (
            self._process,
            self._socket,
            self._reader,
            self._thread,
            self._stderr_thread,
        )
        self._process = None
        self._socket = None
        self._reader = None
        self._thread = None
        self._stderr_thread = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1.0)
        if process is not None and process.stderr is not None:
            process.stderr.close()
        if reader is not None:
            reader.close()
        if stream is not None:
            stream.close()
        if thread is not None:
            thread.join(timeout=1.0)

    def __enter__(self) -> "XVisioStream":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
