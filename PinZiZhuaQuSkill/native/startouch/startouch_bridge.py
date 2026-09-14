#!/usr/bin/env python3
"""Contained Startouch JSON-Lines bridge with an offline simulator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import sys
import time
from typing import Any, Callable, Iterable, TextIO

sys.dont_write_bytecode = True
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))
    from native.startouch.backends import (
        BackendError,
        SdkBackend,
        SdkBackendConfig,
        SimulatedBackend,
    )
    from native.startouch.protocol import (
        COMMANDS,
        LOW_LEVEL_PROTOCOL,
        POSE_FRAME,
        PROTOCOL_SCHEMA,
        ProtocolError,
        STATE_UNITS,
        valid_content_id,
        validate_command,
    )
    from native.startouch.vendor_runtime import (
        StartouchRuntimeError,
        validate_startouch_runtime,
    )
else:
    from .backends import BackendError, SdkBackend, SdkBackendConfig, SimulatedBackend
    from .protocol import (
        COMMANDS,
        LOW_LEVEL_PROTOCOL,
        POSE_FRAME,
        PROTOCOL_SCHEMA,
        ProtocolError,
        STATE_UNITS,
        valid_content_id,
        validate_command,
    )
    from .vendor_runtime import StartouchRuntimeError, validate_startouch_runtime


def _content_id(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def bridge_content_id() -> str:
    """Bind the handshake to the project-local bridge source files."""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in (
        "protocol.py", "vendor_runtime.py", "backends.py", "startouch_bridge.py",
    ):
        data = (root / name).read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def runtime_config_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return _content_id(canonical)


class BridgeRuntime:
    """Validate commands, call one backend, and emit correlated evidence."""

    def __init__(
        self,
        backend: Any,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        bridge_content_id: str,
        runtime_config_id: str,
    ) -> None:
        if not valid_content_id(bridge_content_id) or not valid_content_id(
            runtime_config_id
        ):
            raise ValueError("bridge content identifiers are invalid")
        self.backend = backend
        self.monotonic_ns = monotonic_ns
        self.bridge_content_id = bridge_content_id
        self.runtime_config_id = runtime_config_id
        self._seen_request_ids: set[str] = set()
        self._state_sequence = 0
        self._producer_monotonic_ns = 0
        self._started = False

    def start_events(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._started:
            raise RuntimeError("bridge_already_started")
        self.backend.connect()
        self._started = True
        ready = {
            "type": "bridge_ready",
            "schema": PROTOCOL_SCHEMA,
            "protocol_version": LOW_LEVEL_PROTOCOL,
            "commands": sorted(COMMANDS),
            "correlated_completions": True,
            "pose_frame": POSE_FRAME,
            "software_stop_ack": True,
            "stop_proof_mode": "cleanup_ack_only",
            "state_units": dict(sorted(STATE_UNITS.items())),
            "state_stream": {
                "producer_monotonic_ns": "uint53",
                "sequence": "uint53",
                "strictly_increasing": True,
            },
            "bridge_content_id": self.bridge_content_id,
            "runtime_config_id": self.runtime_config_id,
            "runtime_identity": {
                "runtime_manifest_id": self.backend.runtime_manifest_id,
                "safety_config_sha256": self.backend.safety_config_sha256,
                "safety_profile_id": self.backend.safety_profile_id,
                "startup_feedback_ids": list(self.backend.startup_feedback_ids),
            },
        }
        return ready, self.state_event()

    def state_event(self) -> dict[str, Any]:
        state = self.backend.state()
        self._state_sequence += 1
        timestamp = int(self.monotonic_ns())
        if timestamp <= self._producer_monotonic_ns:
            timestamp = self._producer_monotonic_ns + 1
        self._producer_monotonic_ns = timestamp
        return {
            "type": "robot_state",
            "pose_frame": POSE_FRAME,
            "state_sequence": self._state_sequence,
            "producer_monotonic_ns": timestamp,
            **state,
        }

    def run_line(self, line: str) -> tuple[dict[str, Any], ...]:
        request_id: str | None = None
        command_name: str | None = None
        try:
            message = json.loads(line)
            if isinstance(message, dict):
                request_id = message.get("request_id")
                command_name = message.get("cmd")
            command = validate_command(message)
        except (json.JSONDecodeError, ProtocolError, TypeError) as error:
            return ({
                "type": "error",
                "command": command_name if isinstance(command_name, str) else None,
                "request_id": request_id if isinstance(request_id, str) else None,
                "reason": str(error) or "robot_message_invalid",
            },)
        if command.request_id in self._seen_request_ids:
            return ({
                "type": "error",
                "command": command.cmd,
                "request_id": command.request_id,
                "reason": "request_id_duplicate",
            },)
        self._seen_request_ids.add(command.request_id)
        accepted = {
            "type": "command_accepted",
            "command": command.cmd,
            "request_id": command.request_id,
        }
        boundary_sequence = self._state_sequence
        boundary_ns = self._producer_monotonic_ns
        try:
            result = self.backend.execute(command)
        except BackendError as error:
            return (accepted, {
                "type": "error",
                "command": command.cmd,
                "request_id": command.request_id,
                "reason": str(error),
            })
        completion = {
            "type": "command_complete",
            "command": command.cmd,
            "request_id": command.request_id,
            **result,
        }
        if (
            command.cmd == "software_stop"
            and result.get("cleanup_acknowledged") is True
        ):
            completion["applied_state_sequence"] = boundary_sequence
            completion["applied_producer_monotonic_ns"] = boundary_ns
            return accepted, completion
        if command.cmd == "disconnect":
            return accepted, completion
        return accepted, completion, self.state_event()


def _isolate_protocol_stdout() -> TextIO:
    """Keep fd 1 as JSON-only even when the vendor SDK prints to stdout."""
    sys.stdout.flush()
    protocol_fd = os.dup(sys.stdout.fileno())
    os.set_inheritable(protocol_fd, False)
    try:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    except Exception:
        os.close(protocol_fd)
        raise
    return os.fdopen(protocol_fd, "w", encoding="utf-8", buffering=1)


def _emit_many(
    events: Iterable[dict[str, Any]], *, output: TextIO | None = None,
) -> None:
    stream = sys.stdout if output is None else output
    for event in events:
        print(
            json.dumps(event, sort_keys=True, separators=(",", ":")),
            file=stream,
            flush=True,
        )


def _run_stdio(
    runtime: BridgeRuntime, state_period_ms: int, *, output: TextIO | None = None,
) -> int:
    _emit_many(runtime.start_events(), output=output)
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin, selectors.EVENT_READ)
    next_state = time.monotonic() + state_period_ms / 1000.0
    while True:
        timeout = max(0.0, next_state - time.monotonic())
        events = selector.select(timeout)
        if events:
            line = sys.stdin.readline()
            if line == "":
                return 0
            if line.strip():
                _emit_many(runtime.run_line(line), output=output)
        now = time.monotonic()
        if now >= next_state and runtime.backend.connected:
            _emit_many((runtime.state_event(),), output=output)
            next_state = now + state_period_ms / 1000.0


def _self_test(runtime: BridgeRuntime) -> int:
    runtime.start_events()
    runtime.run_line(json.dumps({
        "cmd": "get_state", "request_id": "self-test-state",
    }))
    stop_events = runtime.run_line(json.dumps({
        "cmd": "software_stop", "request_id": "self-test-stop",
    }))
    completion = stop_events[1]
    ok = (
        completion.get("cleanup_acknowledged") is True
        and completion.get("depower_independently_confirmed") is False
        and runtime.backend.connected is False
    )
    print(json.dumps({
        "hardware_connected": False,
        "ok": ok,
        "vendor_sdk_imported": "startouch" in sys.modules,
    }, sort_keys=True))
    return 0 if ok else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--simulate",
        action="store_true",
        help="Use the deterministic in-memory backend; never import the vendor SDK.",
    )
    mode.add_argument(
        "--real",
        action="store_true",
        help="Use the installed SDK after exact supervised-motion authorization.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a bounded simulation check and exit.",
    )
    parser.add_argument("--state-period-ms", type=int, default=100)
    parser.add_argument("--runtime-root")
    parser.add_argument("--source-manifest")
    parser.add_argument("--expected-safety-config-sha256")
    parser.add_argument("--can-interface", default="can0")
    parser.add_argument("--lock-file")
    parser.add_argument("--gripper-max-width-m", type=float, default=0.080)
    parser.add_argument("--allow-real")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.simulate and not args.real:
        print(json.dumps({
            "type": "bridge_error", "reason": "backend_mode_required",
        }), file=sys.stderr)
        return 2
    if not 20 <= args.state_period_ms <= 1000:
        print(json.dumps({
            "type": "bridge_error", "reason": "state_period_ms_invalid",
        }), file=sys.stderr)
        return 2
    if args.real and args.allow_real != "I_ACCEPT_SUPERVISED_ROBOT_MOTION":
        print(json.dumps({
            "type": "bridge_error",
            "reason": "real_robot_authorization_missing",
        }, sort_keys=True), file=sys.stderr)
        return 2
    if args.real and (
        not isinstance(args.runtime_root, str)
        or not args.runtime_root
        or not isinstance(args.source_manifest, str)
        or not args.source_manifest
        or not isinstance(args.expected_safety_config_sha256, str)
        or len(args.expected_safety_config_sha256) != 64
        or not isinstance(args.lock_file, str)
        or not args.lock_file
    ):
        print(json.dumps({
            "type": "bridge_error", "reason": "real_backend_config_missing",
        }, sort_keys=True), file=sys.stderr)
        return 2
    validated_runtime = None
    if args.real:
        runtime_root = Path(args.runtime_root).expanduser().resolve()
        source_manifest = Path(args.source_manifest).expanduser().resolve()
        if (
            PROJECT_ROOT not in runtime_root.parents
            or PROJECT_ROOT not in source_manifest.parents
        ):
            print(json.dumps({
                "type": "bridge_error", "reason": "runtime_not_project_contained",
            }, sort_keys=True), file=sys.stderr)
            return 2
        try:
            validated_runtime = validate_startouch_runtime(
                runtime_root, source_manifest
            )
            if (
                validated_runtime.config_sha256
                != args.expected_safety_config_sha256
            ):
                raise StartouchRuntimeError("configured_safety_config_mismatch")
            if not validated_runtime.reproducible_build_verified:
                raise StartouchRuntimeError(
                    "startouch_binary_provenance_unverified"
                )
            library_path = os.environ.get("LD_LIBRARY_PATH", "").split(
                os.pathsep
            )[0]
            if (
                not library_path
                or Path(library_path).expanduser().resolve()
                != validated_runtime.library_dir
            ):
                raise StartouchRuntimeError(
                    "runtime_library_path_not_contained"
                )
        except StartouchRuntimeError as error:
            print(json.dumps({
                "type": "bridge_error", "reason": str(error),
            }, sort_keys=True), file=sys.stderr)
            return 2
    runtime_settings = {
        "backend": "simulate" if args.simulate else "startouch_sdk",
        "can_interface": None if args.simulate else args.can_interface,
        "gripper_max_width_m": args.gripper_max_width_m,
        "lock_file": None if args.simulate else str(Path(args.lock_file).resolve()),
        "runtime_manifest_id": (
            None if args.simulate
            else "sha256:" + validated_runtime.runtime_manifest_sha256
        ),
        "runtime_root": (
            None if args.simulate else str(validated_runtime.root)
        ),
        "safety_config_sha256": (
            None if args.simulate else validated_runtime.config_sha256
        ),
        "safety_profile_id": (
            None if args.simulate else validated_runtime.profile_id
        ),
        "source_manifest": (
            None if args.simulate else str(source_manifest)
        ),
        "state_period_ms": args.state_period_ms,
    }
    config_id = runtime_config_id(runtime_settings)
    backend: Any
    if args.simulate:
        backend = SimulatedBackend(
            gripper_max_width_m=args.gripper_max_width_m
        )
    else:
        try:
            backend = SdkBackend(SdkBackendConfig(
                runtime=validated_runtime,
                can_interface=args.can_interface,
                lock_file=Path(args.lock_file),
                gripper_max_width_m=args.gripper_max_width_m,
            ))
        except (TypeError, ValueError) as error:
            print(json.dumps({
                "type": "bridge_error", "reason": str(error),
            }, sort_keys=True), file=sys.stderr)
            return 2
    runtime = BridgeRuntime(
        backend,
        bridge_content_id=bridge_content_id(),
        runtime_config_id=config_id,
    )
    if args.self_test:
        if not args.simulate:
            print(json.dumps({
                "type": "bridge_error", "reason": "real_self_test_forbidden",
            }, sort_keys=True), file=sys.stderr)
            return 2
        return _self_test(runtime)
    protocol_output: TextIO | None = None
    if args.real:
        try:
            protocol_output = _isolate_protocol_stdout()
        except OSError:
            print(json.dumps({
                "type": "bridge_error", "reason": "protocol_output_isolation_failed",
            }, sort_keys=True), file=sys.stderr)
            return 1
    try:
        return _run_stdio(runtime, args.state_period_ms, output=protocol_output)
    except BackendError as error:
        print(json.dumps({
            "type": "bridge_error", "reason": str(error),
        }, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if isinstance(backend, SdkBackend):
            backend.force_release_for_process_exit()
        if protocol_output is not None:
            protocol_output.close()


if __name__ == "__main__":
    raise SystemExit(main())
