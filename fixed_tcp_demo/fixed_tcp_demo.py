#!/usr/bin/env python3
"""Request the existing port-3000 owner to run the unchanged fixed-TCP demo."""

import argparse
import json
import os
from uuid import uuid4

from websockets.sync.client import connect


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the fixed-TCP demo through port 3000")
    parser.add_argument("--execute", action="store_true", help="allow real movement")
    parser.add_argument("--no-dry-run", action="store_true", help="required with --execute")
    parser.add_argument("--fixed-xyz", nargs=3, type=float, default=[0.48, 0.0, 0.36])
    parser.add_argument("--use-current-tcp", action="store_true")
    parser.add_argument("--max-cone-deg", type=float, default=50.0)
    parser.add_argument("--duration-sec", type=float, default=60.0)
    parser.add_argument("--robot-ws-url", default=os.environ.get("ROBOT_WS_URL", "ws://127.0.0.1:3000/ws"))
    args = parser.parse_args(argv)
    if args.execute != args.no_dry_run:
        parser.error("real movement requires both --execute and --no-dry-run")
    request_id = uuid4().hex
    try:
        with connect(args.robot_ws_url, open_timeout=5) as socket:
            socket.send(json.dumps({
                "cmd": "fixed_tcp_demo", "request_id": request_id,
                "execute": args.execute, "fixed_xyz": args.fixed_xyz,
                "use_current_tcp_xyz": args.use_current_tcp,
                "max_cone_deg": args.max_cone_deg, "duration_sec": args.duration_sec,
            }))
            accepted = False
            try:
                while True:
                    message = json.loads(socket.recv(timeout=180))
                    if message.get("request_id") != request_id:
                        continue
                    if message.get("type") == "error":
                        print("ERROR:", message.get("msg") or message.get("message") or message.get("code"))
                        return 1
                    if message.get("type") == "command_status":
                        print(f"3000 fixed-TCP demo: {message.get('status')}", flush=True)
                        if message.get("status") == "accepted":
                            accepted = True
                        if message.get("status") == "complete":
                            return 0
            except BaseException:
                if accepted:
                    socket.send(json.dumps({"cmd": "software_stop"}))
                raise
    except KeyboardInterrupt:
        print("Stop requested through port 3000.")
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
