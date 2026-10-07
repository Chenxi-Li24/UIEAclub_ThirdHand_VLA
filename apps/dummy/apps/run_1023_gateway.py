#!/usr/bin/env python3
"""Run the 1023 debug gateway on port 31023.

The gateway never talks to CAN or the SDK.  It accepts a narrow WebSocket
surface on 127.0.0.1:31023/ws and forwards only filtered commands to the
existing Robot Service on 127.0.0.1:3000.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.gateway_1023 import Gateway1023Policy
from dummy.robot_ws_client import RobotWebSocketClient


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run 1023/31023 robot debug gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=31023)
    parser.add_argument("--robot-ws", default="ws://127.0.0.1:3000/ws")
    parser.add_argument("--robot-health", default="http://127.0.0.1:3000/health")
    parser.add_argument("--max-delta-deg", type=float, default=0.0, help="0 disables the extra 31023 relative-step limiter")
    parser.add_argument("--min-interval-s", type=float, default=0.0, help="0 disables the extra 31023 rate limiter")
    return parser.parse_args(argv)


class Gateway1023Server:
    def __init__(self, args):
        self.args = args

    async def handler(self, websocket):
        robot = RobotWebSocketClient(self.args.robot_ws, self.args.robot_health)
        policy = Gateway1023Policy(
            max_delta_deg=None if self.args.max_delta_deg <= 0 else self.args.max_delta_deg,
            min_interval_s=self.args.min_interval_s,
        )

        async def relay_robot_events():
            last_index = 0
            while True:
                await asyncio.sleep(0.02)
                while last_index < len(robot.events):
                    event = robot.events[last_index]
                    last_index += 1
                    await websocket.send(json.dumps(event, separators=(",", ":")))

        relay = None
        try:
            await robot.open()
            await robot.command("status")
            relay = asyncio.create_task(relay_robot_events())
            await websocket.send(json.dumps({
                "type": "gateway_1023",
                "status": "ready",
                "port": self.args.port,
                "robot_ws": self.args.robot_ws,
                "allowed": ["connect", "disconnect", "preset zero", "preset home", "move_joint", "servo", "status", "get_state", "software_stop", "ping"],
                "blocked": ["force", "set_joint_raw", "move_l", "other presets", "raw_can"],
                "max_delta_deg": self.args.max_delta_deg,
                "min_interval_s": self.args.min_interval_s,
            }, separators=(",", ":")))

            async for raw in websocket:
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "type": "error", "code": "json_invalid", "msg": "message must be JSON",
                    }, separators=(",", ":")))
                    continue

                result = policy.validate(
                    message,
                    robot.snapshot.joints_deg,
                    now=time.time(),
                )
                if not result.ok:
                    print(f"[1023] rejected {message.get('cmd')} code={result.code} reason={result.reason}", flush=True)
                    error = {
                        "type": "error",
                        "code": result.code,
                        "msg": result.reason,
                    }
                    if isinstance(message.get("request_id"), str):
                        error["request_id"] = message["request_id"]
                    await websocket.send(json.dumps(error, separators=(",", ":")))
                    continue
                await robot.command(**result.message)
                if isinstance(result.message.get("request_id"), str):
                    await websocket.send(json.dumps({
                        "type": "motion_ack",
                        "status": "forwarded",
                        "command": result.message["cmd"],
                        "request_id": result.message["request_id"],
                        "gateway_port": self.args.port,
                    }, separators=(",", ":")))
                joints = result.message.get("joints_deg", result.message.get("joints"))
                print(
                    "[1023] forwarded "
                    f"{result.message['cmd']} request_id={result.message.get('request_id')} q={joints} "
                    f"time={result.message.get('time_sec')}",
                    flush=True,
                )
        finally:
            if relay is not None:
                relay.cancel()
            await robot.close()

    async def run(self):
        async with websockets.serve(self.handler, self.args.host, self.args.port):
            print(
                f"[1023] gateway listening on ws://{self.args.host}:{self.args.port}/ws "
                f"-> {self.args.robot_ws}",
                flush=True,
            )
            await asyncio.Future()


def run(argv=None):
    args = parse_args(argv)
    try:
        asyncio.run(Gateway1023Server(args).run())
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
