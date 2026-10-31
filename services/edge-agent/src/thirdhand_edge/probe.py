"""Explicit, bounded no-hardware connectivity probe."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tomllib
import uuid
import time

from .transport import DeviceConfig, connect_device
from .probe_measurements import ProbeMeasurements


async def run_probe(values, *, heartbeats=None, duration_seconds=None, cycles=1):
    measurements = ProbeMeasurements()
    connections = set()
    completed = 0
    started = time.monotonic()

    async def observe(message):
        if message["type"] == "connected":
            if message.get("controlAuthorized") is not False or message["context"]["executorEpoch"] is not None:
                raise ValueError("Probe authority rejected")
            connection_id = message["context"]["connectionId"]
            if connection_id in connections:
                raise ValueError("Reused probe connection")
            connections.add(connection_id)
        elif message["type"] == "heartbeat":
            measurements.add(message["rttMs"], time.monotonic_ns())

    try:
        for _ in range(cycles):
            config = DeviceConfig(**values, boot_id=str(uuid.uuid4()))
            await connect_device(config, observe, probe_count=heartbeats,
                                 probe_duration_seconds=duration_seconds / cycles if duration_seconds else None)
            completed += 1
    except Exception:
        # An unexpected failure ends the run. Only successful planned cycles reconnect.
        pass
    success = completed == cycles
    return {"connected": bool(connections), "completed": success, "completedCycles": completed,
            "uniqueConnections": len(connections), "controlAuthorized": False, "mode": "probe-only",
            "elapsedSeconds": round(time.monotonic() - started, 3),
            "measurements": measurements.report(), **({} if success else {"error": "DEVICE_PROBE_FAILED"})}


def main():
    parser = argparse.ArgumentParser(description="ThirdHand outbound mTLS probe; no SDK/CAN/camera")
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--heartbeats", type=int)
    mode.add_argument("--duration-seconds", type=int)
    parser.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args()
    if args.heartbeats is not None and not 1 <= args.heartbeats <= 1800:
        parser.error("heartbeats must be 1..1800")
    if args.duration_seconds is not None and not 1 <= args.duration_seconds <= 3600:
        parser.error("duration-seconds must be 1..3600")
    if not 1 <= args.cycles <= 6 or args.cycles != 1 and args.duration_seconds is None:
        parser.error("cycles must be 1..6 and require duration-seconds")
    try:
        source = tomllib.loads(args.config.read_text(encoding="utf-8"))
        if set(source) - {"url", "device_id", "certificate", "private_key", "ca_file"}:
            raise ValueError("Unknown configuration field")
        values = dict(source)
        for name in ("certificate", "private_key", "ca_file"):
            if name in values:
                values[name] = (args.config.parent / values[name]).resolve()
        result = asyncio.run(run_probe(values, heartbeats=args.heartbeats or (15 if args.duration_seconds is None else None),
                                      duration_seconds=args.duration_seconds, cycles=args.cycles))
        print(json.dumps(result))
        if not result["completed"]:
            raise SystemExit(1)
    except (Exception, KeyboardInterrupt):
        # No PEM material, URLs, raw frames, headers or third-party exception text in logs.
        print(json.dumps({"connected": False, "error": "DEVICE_PROBE_FAILED"}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
