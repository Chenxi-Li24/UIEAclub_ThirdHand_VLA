#!/usr/bin/env python3
"""Ubuntu-local Start/Stop dashboard for the fixed Pick and Place demo."""

from __future__ import annotations

import argparse
from collections import deque
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
from typing import Any, Callable
from urllib.parse import urlparse


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766


class DemoController:
    """Own exactly one demo subprocess without directly opening can0."""

    def __init__(
        self,
        root: Path,
        *,
        popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        killpg: Callable[[int, int], None] = os.killpg,
    ) -> None:
        self.root = Path(root).resolve()
        self._popen_factory = popen_factory
        self._killpg = killpg
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._last_pid: int | None = None
        self._state = "IDLE"
        self._stage = "IDLE"
        self._message = "等待开始"
        self._last_log: str | None = None
        self._log_tail: deque[str] = deque(maxlen=500)
        self._stop_requested = False
        self._resource_conflict = False
        self._run_mode: str | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            owned = process is not None and process.poll() is None
            return {
                "state": self._state,
                "stage": self._stage,
                "message": self._message,
                "pid": process.pid if owned else self._last_pid,
                "owned": owned,
                "run_mode": self._run_mode,
                "log_tail": list(self._log_tail),
                "last_log": self._last_log,
            }

    def start(self, mode: str = "manual") -> bool:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return False
            if mode not in {"manual", "automatic-three-cycle"}:
                self._state = "FAILED"
                self._stage = "MODE_CHECK"
                self._message = f"不支持的运行模式：{mode}"
                return False
            self._state = "PREFLIGHT"
            self._stage = "RESOURCE_PREFLIGHT"
            self._message = "正在执行安全检查"
            self._last_log = None
            self._log_tail.clear()
            self._stop_requested = False
            self._resource_conflict = False
            env = os.environ.copy()
            if mode == "automatic-three-cycle":
                env.update(
                    {
                        "DEMO_RUN_MODE": "automatic-three-cycle",
                        "DEMO_CYCLES": "3",
                        "DEMO_CONFIRM_EACH_STEP": "0",
                    }
                )
            try:
                process = self._popen_factory(
                    [
                        "bash",
                        str(self.root / "scripts" / "demo_fixed_pick_place.sh"),
                    ],
                    cwd=str(self.root),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                    env=env,
                )
            except OSError as exc:
                self._state = "FAILED"
                self._stage = "PROCESS_LAUNCH"
                self._message = f"无法启动演示进程：{exc}"
                self._run_mode = None
                return False
            self._process = process
            self._last_pid = process.pid
            self._run_mode = mode
            monitor = threading.Thread(
                target=self._monitor,
                args=(process,),
                daemon=True,
            )
            monitor.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return False
            self._stop_requested = True
            self._state = "STOPPING"
            self._stage = "SOFTWARE_STOP"
            self._message = "正在中断演示、cleanup 并失能"
            pid = process.pid
        try:
            self._killpg(pid, signal.SIGINT)
        except ProcessLookupError:
            with self._lock:
                self._state = "STOPPED"
                self._stage = "SOFTWARE_STOP"
                self._message = "演示进程已经退出"
            return False
        except OSError as exc:
            with self._lock:
                self._state = "FAILED"
                self._stage = "SOFTWARE_STOP"
                self._message = f"无法发送停止信号：{exc}"
            return False
        return True

    def continue_step(self) -> bool:
        with self._lock:
            process = self._process
            if (
                process is None
                or process.poll() is not None
                or self._state != "WAITING_CONFIRMATION"
                or self._run_mode != "manual"
                or process.stdin is None
            ):
                return False
            try:
                process.stdin.write("\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                self._state = "FAILED"
                self._stage = "CONFIRMATION_CHANNEL"
                self._message = f"确认通道不可用：{exc}"
                return False
            self._state = "RUNNING"
            self._message = "已确认，正在执行当前步骤"
            return True

    def _consume_line(self, raw_line: str) -> None:
        line = raw_line.rstrip("\r\n")
        if not line:
            return
        with self._lock:
            self._log_tail.append(line)
            if line.startswith("AWAITING_CONFIRMATION="):
                self._state = "WAITING_CONFIRMATION"
                self._stage = line.split("=", 1)[1] or "UNKNOWN"
                self._message = "等待现场人员点击“执行下一步”"
            elif line == "RESOURCE_CONFLICT":
                self._resource_conflict = True
                self._state = "FAILED"
                self._message = "RESOURCE_CONFLICT"
            elif line.startswith("FAILED_STAGE="):
                self._stage = line.split("=", 1)[1] or "UNKNOWN"
            elif line.startswith("ERROR_REASON="):
                reason = line.split("=", 1)[1]
                if not self._resource_conflict:
                    self._message = reason
            elif line.startswith("LOG=") or line.startswith("RUNNER_LOG="):
                self._last_log = line.split("=", 1)[1]
            elif line == "PICK AND PLACE COMPLETE":
                self._state = "COMPLETE"
                self._stage = "COMPLETE"
                self._message = "PICK AND PLACE COMPLETE"
            elif line == "PICK AND PLACE FAILED":
                self._state = "FAILED"
                if not self._resource_conflict:
                    self._message = "PICK AND PLACE FAILED"
            elif line.startswith("RUN_COMMAND=") or " STATE " in line:
                self._state = "RUNNING"
                self._message = "机械臂任务执行中"
            elif line in {"3...", "2...", "1..."}:
                self._state = "COUNTDOWN"
                self._stage = "COUNTDOWN"
                self._message = f"启动倒计时 {line}"

    def _monitor(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                self._consume_line(line)
        returncode = process.wait()
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
        with self._lock:
            if process is not self._process:
                return
            if self._stop_requested or returncode == -signal.SIGINT:
                self._state = "STOPPED"
                self._stage = "SOFTWARE_STOP"
                self._message = "已停止；cleanup 和失能流程已执行"
            elif returncode == 0:
                if self._state != "COMPLETE":
                    self._state = "COMPLETE"
                    self._stage = "COMPLETE"
                    self._message = "PICK AND PLACE COMPLETE"
            else:
                self._state = "FAILED"
                if self._resource_conflict:
                    self._message = "RESOURCE_CONFLICT"
                elif self._message not in {
                    "PICK AND PLACE FAILED",
                }:
                    self._message = f"演示进程退出，代码 {returncode}"
            self._process = None
            self._run_mode = None


class DemoRequestHandler(SimpleHTTPRequestHandler):
    controller: DemoController
    static_dir: Path

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.static_dir), **kwargs)

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/status":
            self._json(HTTPStatus.OK, self.controller.status())
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/start":
            started = self.controller.start("manual")
            self._json(
                HTTPStatus.ACCEPTED if started else HTTPStatus.CONFLICT,
                {"accepted": started, **self.controller.status()},
            )
            return
        if path == "/api/start-auto":
            started = self.controller.start("automatic-three-cycle")
            self._json(
                HTTPStatus.ACCEPTED if started else HTTPStatus.CONFLICT,
                {"accepted": started, **self.controller.status()},
            )
            return
        if path == "/api/stop":
            stopped = self.controller.stop()
            self._json(
                HTTPStatus.ACCEPTED if stopped else HTTPStatus.CONFLICT,
                {"accepted": stopped, **self.controller.status()},
            )
            return
        if path == "/api/continue":
            continued = self.controller.continue_step()
            self._json(
                HTTPStatus.ACCEPTED if continued else HTTPStatus.CONFLICT,
                {"accepted": continued, **self.controller.status()},
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[http] {self.address_string()} {format % args}", flush=True)


def create_server(
    controller: DemoController,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> ThreadingHTTPServer:
    handler = type(
        "BoundDemoRequestHandler",
        (DemoRequestHandler,),
        {
            "controller": controller,
            "static_dir": controller.root / "web-control" / "demo",
        },
    )
    return ThreadingHTTPServer((host, port), handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--open-browser", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parents[2]
    controller = DemoController(root)
    server = create_server(controller, args.host, args.port)
    url = f"http://{args.host}:{args.port}/"
    print(f"Fixed Pick and Place Control: {url}", flush=True)
    if args.open_browser:
        try:
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            print(f"浏览器打开失败，请手动访问 {url}: {exc}", flush=True)

    def request_shutdown(_signum=None, _frame=None):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
