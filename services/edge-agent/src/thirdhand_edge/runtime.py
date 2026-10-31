"""Transport supervisor: control, capture and upload have independent processes.

Systemd may restart this supervisor after network loss. Each restart mints a new
boot ID; no control lease or physical command is restored or retried.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tomllib
import traceback
import uuid

from .bound_transport import connect_bound_device
from .capture import capture_stream
from .journal import CommandJournal
from .outbox import Outbox
from .robot_client import RobotClient
from .transport import DeviceConfig
from .transport import connect_device
from .upload import TelemetryUploadClient


def load_runtime_config(path):
    path = Path(path).resolve()
    value = tomllib.loads(path.read_text(encoding="utf-8"))
    required = {"url", "device_id", "certificate", "private_key", "robot_origin", "robot_token_file", "signing_keys_file", "state_directory"}
    media_fields={"media_source_url", "media_token_file", "media_server_url"}
    if set(value) - (required | {"ca_file", "outbox_max_bytes", "versions"} | media_fields) or not required <= set(value) or set(value) & media_fields and not media_fields <= set(value):
        raise ValueError("Invalid runtime configuration fields")
    for key in required | {"ca_file"} | media_fields:
        if key in value and (not isinstance(value[key], str) or not value[key] or "\0" in value[key]):
            raise ValueError("Invalid runtime string")
    for key in ("certificate", "private_key", "ca_file", "robot_token_file", "signing_keys_file", "state_directory", "media_token_file"):
        if key in value:
            value[key] = (path.parent / value[key]).resolve()
    versions = value.get("versions", {})
    if not isinstance(versions, dict) or set(versions) - {"schema", "tool", "calibration", "sdk", "framePolicy"} or any(not isinstance(item, (str, int)) or isinstance(item, bool) for item in versions.values()):
        raise ValueError("Invalid version metadata")
    # Validate the public transport endpoint now, without reading credentials or
    # connecting to the Robot Service, network, SDK or camera.
    DeviceConfig(url=value["url"], device_id=value["device_id"], boot_id=str(uuid.uuid4()), certificate=value["certificate"], private_key=value["private_key"], ca_file=value.get("ca_file"))
    capacity = value.get("outbox_max_bytes", 268435456)
    if type(capacity) is not int or not 262144 <= capacity <= 17179869184:
        raise ValueError("Invalid outbox capacity")
    return value


def _state_directory(config):
    directory = config["state_directory"]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or directory.resolve() != directory or os.name == "posix" and directory.stat().st_mode & 0o077:
        raise ValueError("Owner-only state directory required")
    return directory


def run_worker(config, role, boot):
    directory = _state_directory(config)
    device = DeviceConfig(url=config["url"], device_id=config["device_id"], boot_id=boot, certificate=config["certificate"], private_key=config["private_key"], ca_file=config.get("ca_file"))
    if role in ("control", "media"):
        keys = json.loads(config["signing_keys_file"].read_text(encoding="utf-8"))
        if not isinstance(keys, dict) or not keys or len(keys) > 4 or any(not isinstance(key, str) or not isinstance(value, str) for key, value in keys.items()):
            raise ValueError("Invalid cloud signing keys")
        robot = RobotClient(base_url=config["robot_origin"], token_file=config["robot_token_file"])
    if role == "control":
        journal = CommandJournal(directory / "commands.sqlite")
        async def save_context(context):
            temporary=directory / "connection.json.tmp"
            temporary.write_text(json.dumps(context),encoding="utf-8")
            temporary.replace(directory / "connection.json")
        async def transport():
            snapshot=await robot.get_context()
            if snapshot.get("bindingAccepted",snapshot.get("controlAccepted")) is True:
                await connect_bound_device(device,robot=robot,trusted_keys=keys,journal=journal,on_context=save_context)
            else:
                async def message(value):
                    if value.get("type")=="connected":
                        await save_context(value["context"])
                await connect_device(device,on_message=message)
        try:
            asyncio.run(transport())
        finally:
            journal.close()
        return
    if role == "media":
        from urllib.parse import urlsplit
        from .frames import LocalCameraSource
        from .media_upload import MediaGrantClient
        from .media_publisher import publish_camera
        parsed=urlsplit(config["media_server_url"])
        if parsed.scheme!="wss" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path!="/media":
            raise ValueError("Exact WSS media signal base required")
        source=LocalCameraSource(url=config["media_source_url"],token_file=config["media_token_file"])
        grants=MediaGrantClient(device)
        async def publish():
            deadline=time.monotonic()+10
            while True:
                try:
                    context=json.loads((directory / "connection.json").read_text(encoding="utf-8"))
                    if context.get("deviceId")==device.device_id and context.get("bootId")==boot:
                        break
                except (OSError,ValueError):
                    pass
                if time.monotonic()>=deadline:
                    raise ValueError("Current authenticated device context unavailable")
                await asyncio.sleep(0.1)
            iterator=source.iter_frames()
            async def frames():
                try:
                    while True:
                        frame=await asyncio.to_thread(next,iterator,None)
                        if frame is None:
                            return
                        yield frame
                finally:
                    try:
                        iterator.close()
                    except ValueError:
                        pass  # a pending read has a bounded3s socket timeout
            async def received(envelope):
                if context.get("executorEpoch") is not None:
                    await robot.report_media_health(envelope)
            await publish_camera(frames=frames(),request_grant=grants.request,context=context,publisher_id=str(uuid.uuid4()),trusted_keys=keys,server_url=config["media_server_url"],on_grant=received)
        asyncio.run(publish())
        return
    box = Outbox(directory / "outbox.sqlite", device_id=device.device_id, boot_id=boot, max_bytes=config.get("outbox_max_bytes", 268435456))
    try:
        if role == "capture":
            robot = RobotClient(base_url=config["robot_origin"], token_file=config["robot_token_file"])
            capture_stream(robot, box, versions=config.get("versions"))
        elif role == "upload":
            client = TelemetryUploadClient(device)
            async def loop():
                while True:
                    result = await client.upload_pending(box)
                    # Yield between bounded rounds, but do not add a second of
                    # latency for each twenty batches while backlog remains.
                    delay = 5 if result.get("error") else 0 if box.pending_batches(limit=1) else 1
                    await asyncio.sleep(delay)
            try:
                asyncio.run(loop())
            finally:
                client.close()
        else:
            raise ValueError("Invalid worker role")
    finally:
        box.close()


def supervise(path, config):
    if os.name != "posix":
        raise ValueError("Production supervisor requires Linux process locking")
    import fcntl
    directory = _state_directory(config)
    lock = (directory / "supervisor.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    boot = str(uuid.uuid4())
    box = Outbox(directory / "outbox.sqlite", device_id=config["device_id"], boot_id=boot, max_bytes=config.get("outbox_max_bytes", 268435456))
    try:
        box.seal_retained()
    finally:
        box.close()
    # Local status only. Root Robot Service still mints executor/connection
    # authority and independently verifies every signed request.
    (directory / "current-boot").write_text(boot, encoding="ascii")
    children = []
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    previous = {name: signal.signal(name, stop) for name in (signal.SIGTERM, signal.SIGINT)}
    try:
        for role in ("capture", "upload", "control", *(("media",) if "media_source_url" in config else ())):
            children.append(subprocess.Popen([sys.executable, "-m", "thirdhand_edge.runtime", "--config", str(path), "--worker", role, "--boot", boot], stdin=subprocess.DEVNULL))
        print(json.dumps({"event": "edge.started", "bootId": boot, "controlAuthorized": False}), flush=True)
        while not stopping and all(child.poll() is None for child in children):
            time.sleep(0.1)
        if not stopping:
            raise RuntimeError("Worker exited; new boot required")
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 3
        for child in children:
            try:
                child.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for name, handler in previous.items():
            signal.signal(name, handler)
        lock.close()
        # Process exit is not proof of physical stop; Root watchdog remains the
        # independent authority and an unknown stop still requires onsite work.


def main():
    parser = argparse.ArgumentParser(description="ThirdHand outbound device supervisor; no automatic SDK connection")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--worker", choices=("control", "capture", "upload", "media"), help=argparse.SUPPRESS)
    parser.add_argument("--boot", help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        config = load_runtime_config(args.config)
        if args.worker:
            uuid.UUID(args.boot)
            def interrupted(*_):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, interrupted)
            run_worker(config, args.worker, args.boot)
        else:
            supervise(args.config.resolve(), config)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        # Diagnose service-only failures without exposing headers, tokens,
        # certificate data, request payloads or arbitrary exception messages.
        print(json.dumps({"event": "edge.unavailable", "worker": args.worker or "supervisor",
                          "errorType": type(error).__name__,
                          "statusCode": error.code if isinstance(getattr(error, "code", None), int) else None,
                          "frames": [{"file": Path(frame.filename).name, "line": frame.lineno}
                                     for frame in traceback.extract_tb(error.__traceback__)
                                     if 'thirdhand_edge' in frame.filename][-4:]}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
