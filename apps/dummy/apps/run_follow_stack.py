#!/usr/bin/env python3
"""Start and verify the Dummy person-follow control stack.

This script does not bypass Robot Service.  It keeps the chain as:

    Dummy follow -> TouchR1Adapter -> 3000 Robot Service -> Startouch SDK.

By default it starts/verifies the services only.  Add ``--enable-motion`` to
start the head-body follow loop after Robot Service reports fresh state.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR / "src"))

from dummy.config import load_config
from dummy.touch_r1_adapter import TouchR1Adapter

ROOT = APP_DIR.parents[1]
PYTHON = ROOT / "local" / "runtimes" / "vision-python" / "bin" / "python"
NODE = ROOT / "local" / "runtimes" / "node" / "bin" / "node"
LOG_DIR = APP_DIR / "logs"
RUN_DIR = ROOT / "runtime" / "run"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Start Dummy follow stack")
    parser.add_argument("--enable-motion", action="store_true", help="start real robot follow after checks")
    parser.add_argument("--hz", type=float, default=6.0, help="follow loop rate when --enable-motion is set")
    parser.add_argument("--skip-home", action="store_true", help="debug only: do not return to zero before follow")
    parser.add_argument("--max-frames", type=int, default=0, help="optional follow loop frame limit")
    parser.add_argument("--no-start", action="store_true", help="only diagnose existing services")
    parser.add_argument("--robot-health", default="http://127.0.0.1:3000/health")
    parser.add_argument("--robot-ws", default="ws://127.0.0.1:3000/ws")
    return parser.parse_args(argv)


def http_json(url, timeout=1.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def process_lines(pattern):
    result = subprocess.run(
        ["pgrep", "-af", pattern],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def start_background(name, args, log_name, *, cwd=ROOT, env=None):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / log_name
    log_file = log_path.open("ab")
    process = subprocess.Popen(
        [str(item) for item in args],
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"[stack] started {name} pid={process.pid} log={log_path}", flush=True)
    return process


def ensure_robot_service(args):
    health = http_json(args.robot_health)
    if health is not None:
        print(f"[stack] robot service already up: {summarize_health(health)}", flush=True)
        return
    if args.no_start:
        raise RuntimeError("Robot Service 3000 is not reachable")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    start_background(
        "robot-service-3000",
        [NODE, ROOT / "services" / "robot" / "src" / "server.js"],
        "robot-service-3000.log",
        env={
            "ROBOT_PORT": "3000",
            "THIRDHAND_READY_FILE": str(RUN_DIR / "robot.ready"),
        },
    )
    wait_for(lambda: http_json(args.robot_health), "Robot Service 3000")


def wait_for(fn, label, timeout=8.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(0.2)
    raise RuntimeError(f"{label} did not become ready; last={last!r}")


def summarize_health(health):
    robot = health.get("robot", {}) if isinstance(health, dict) else {}
    return (
        f"connected={robot.get('connected')} "
        f"stateReady={robot.get('stateReady')} "
        f"moving={robot.get('moving')}"
    )


async def _connect_robot(robot_ws, robot_health):
    config = load_config()
    config.setdefault("robot", {}).update(ws_url=robot_ws, health_url=robot_health)
    adapter = TouchR1Adapter(config)
    try:
        state = await adapter.connect()
        if not state.connected or not state.state_ready:
            raise RuntimeError("Robot SDK did not report connected/stateReady")
        return list(state.joints_deg)
    finally:
        # Close this client only; leave the SDK available to the follow loop.
        await adapter.close()


def connect_robot(args):
    joints = asyncio.run(_connect_robot(args.robot_ws, args.robot_health))
    print(
        "[stack] robot SDK ready q=["
        + ", ".join(f"{float(value):.2f}" for value in joints[:6])
        + "]",
        flush=True,
    )


def run_follow(args):
    command = [
        PYTHON,
        APP_DIR / "apps" / "run_head_body_follow.py",
        "--enable-motion",
        "--hz",
        str(args.hz),
        "--robot-ws",
        args.robot_ws,
        "--robot-health",
        args.robot_health,
    ]
    if args.skip_home:
        command.append("--skip-home")
    if args.max_frames:
        command.extend(["--max-frames", str(args.max_frames)])
    process = start_background(
        "head-body-follow",
        command,
        "head-body-follow-live.log",
        cwd=APP_DIR,
    )
    print(f"[stack] follow running pid={process.pid}", flush=True)


def install_signal_handlers():
    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)


def run(argv=None):
    args = parse_args(argv)
    install_signal_handlers()
    try:
        ensure_robot_service(args)
        connect_robot(args)
        health = http_json(args.robot_health) or {}
        print(f"[stack] final robot health: {summarize_health(health)}", flush=True)
        if args.enable_motion:
            run_follow(args)
        else:
            print("[stack] services are ready; add --enable-motion to start follow", flush=True)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"[stack] ERROR: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
