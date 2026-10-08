#!/usr/bin/env python3
"""Run the fail-closed person-follow gateway on loopback port 31023."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.gateway.audit import GatewayAudit
from dummy_legacy.gateway.ownership import LeaseRegistry
from dummy_legacy.gateway.policy import GatewayPolicy
from dummy_legacy.gateway.robot_3000 import Robot3000Adapter
from dummy_legacy.gateway.server import GatewayServer


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=31023, type=int)
    parser.add_argument("--robot-ws", default="ws://127.0.0.1:3000/ws")
    parser.add_argument("--max-step-deg", default=0.75, type=float)
    parser.add_argument("--lease-ttl-s", default=1.0, type=float)
    parser.add_argument("--log", default="logs/person-follow-gateway.jsonl")
    return parser.parse_args(argv)


async def main(argv=None):
    args = parse_args(argv)
    server = GatewayServer(
        GatewayPolicy(args.max_step_deg), LeaseRegistry(args.lease_ttl_s),
        Robot3000Adapter(args.robot_ws), GatewayAudit(args.log), args.host, args.port,
    )
    listener = await server.serve()
    print(f'{{"component":"gateway_31023","event":"listening","url":"ws://{args.host}:{args.port}","upstream":"{args.robot_ws}"}}', flush=True)
    await listener.wait_closed()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
