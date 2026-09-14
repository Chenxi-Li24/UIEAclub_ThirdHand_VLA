"""Content-addressed Startouch preview serialization with no execution path."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..runtime.models import (
    SEMVER_PATTERN,
    Argument,
    CommandReceipt,
    CommandRequest,
    ExecutorKind,
    FrozenModel,
    ReceiptStatus,
)
from .startouch_preview import (
    CommandPreview,
    ShadowLimits,
    StartouchCommandPreview,
)


class PreviewResolutionError(ValueError):
    """Raised when no exact checked preview binding exists for a request."""


class ExecutionCapability(FrozenModel):
    """A capability token whose public schema cannot express real execution."""

    kind: ExecutorKind
    can_execute_world: Literal[False] = False
    robot_execution_enabled: Literal[False] = False

    @classmethod
    def shadow(cls) -> ExecutionCapability:
        return cls(kind=ExecutorKind.SHADOW)

    @classmethod
    def fake(cls) -> ExecutionCapability:
        return cls(kind=ExecutorKind.FAKE)


class PreviewBinding(FrozenModel):
    skill_id: str = Field(min_length=1)
    contract_version: str
    arguments: tuple[Argument, ...]
    policy_id: str = Field(min_length=1)
    policy_version: str
    command: CommandPreview

    @field_validator("contract_version", "policy_version")
    @classmethod
    def semantic_version(cls, value: str) -> str:
        if not SEMVER_PATTERN.fullmatch(value):
            raise ValueError("binding versions must be semantic x.y.z")
        return value

    @model_validator(mode="after")
    def unique_arguments(self) -> PreviewBinding:
        names = [item.name for item in self.arguments]
        if len(names) != len(set(names)):
            raise ValueError("preview binding arguments must be unique")
        return self


class PreviewPolicy(FrozenModel):
    schema_version: str
    robot_execution_enabled: Literal[False]
    bindings: tuple[PreviewBinding, ...] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def semantic_version(cls, value: str) -> str:
        if not SEMVER_PATTERN.fullmatch(value):
            raise ValueError("schema version must be semantic x.y.z")
        return value


def _argument_key(arguments: tuple[Argument, ...]) -> str:
    payload = [
        item.model_dump(mode="json") for item in sorted(arguments, key=lambda item: item.name)
    ]
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


class PreviewResolver:
    """Resolve only exact skill, version, and argument tuples from checked bindings."""

    def __init__(self, bindings: tuple[PreviewBinding, ...]) -> None:
        if not bindings:
            raise ValueError("preview resolver requires at least one binding")
        entries: dict[tuple[str, str, str], PreviewBinding] = {}
        for binding in bindings:
            key = (
                binding.skill_id,
                binding.contract_version,
                _argument_key(binding.arguments),
            )
            if key in entries:
                raise ValueError("duplicate preview binding")
            entries[key] = binding
        self._entries = entries

    def resolve(self, request: CommandRequest) -> StartouchCommandPreview:
        key = (
            request.skill_id,
            request.contract_version,
            _argument_key(request.arguments),
        )
        try:
            binding = self._entries[key]
        except KeyError as exc:
            raise PreviewResolutionError("no exact preview binding for request") from exc
        return StartouchCommandPreview(
            request_id=request.request_id,
            episode_id=request.episode_id,
            step_id=request.step_id,
            attempt=request.attempt,
            policy_id=binding.policy_id,
            policy_version=binding.policy_version,
            contract_version=binding.contract_version,
            command=binding.command,
        )


def load_preview_resolver(path: Path) -> PreviewResolver:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        policy = PreviewPolicy.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"invalid preview policy {path}: {exc}") from exc
    return PreviewResolver(policy.bindings)


class StartouchShadowExecutor:
    """Serialize preview evidence; never import or call robot code."""

    kind = ExecutorKind.SHADOW
    can_execute_world = False

    def __init__(
        self,
        *,
        output_dir: Path,
        resolver: PreviewResolver,
        limits: ShadowLimits,
        capability: ExecutionCapability,
    ) -> None:
        if capability.kind is not ExecutorKind.SHADOW:
            raise ValueError("Startouch shadow executor requires a shadow capability")
        if capability.can_execute_world or capability.robot_execution_enabled:
            raise ValueError("world-changing execution capability is forbidden")
        self._output_dir = Path(output_dir)
        self._resolver = resolver
        self._limits = limits
        self.dispatch_count = 0

    def execute(self, request: CommandRequest) -> CommandReceipt:
        try:
            preview = self._resolver.resolve(request)
            self._limits.validate_preview(preview)
            payload = self._canonical_bytes(preview)
            digest = hashlib.sha256(payload).hexdigest()
            self._write_once(digest, payload)
        except (OSError, PreviewResolutionError, ValueError):
            return CommandReceipt(
                request_id=request.request_id,
                status=ReceiptStatus.REJECTED,
                evidence_ids=(),
            )
        self.dispatch_count += 1
        return CommandReceipt(
            request_id=request.request_id,
            status=ReceiptStatus.COMPLETED,
            evidence_ids=(f"sha256:{digest}",),
        )

    @staticmethod
    def _canonical_bytes(preview: StartouchCommandPreview) -> bytes:
        return json.dumps(
            preview.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def _write_once(self, digest: str, payload: bytes) -> None:
        if self._output_dir.is_symlink():
            raise ValueError("preview directory must not be a symlink")
        if self._output_dir.exists() and not self._output_dir.is_dir():
            raise ValueError("preview output must be a directory")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        destination = self._output_dir / f"{digest}.json"
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise ValueError("preview destination is not a regular file")
            if destination.read_bytes() != payload:
                raise ValueError("content-addressed preview collision")
            return

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix=f".{digest}.",
                suffix=".tmp",
                dir=self._output_dir,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_path, destination, follow_symlinks=False)
            except FileExistsError:
                if destination.is_symlink() or destination.read_bytes() != payload:
                    raise ValueError("content-addressed preview collision") from None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


__all__ = [
    "ExecutionCapability",
    "PreviewBinding",
    "PreviewPolicy",
    "PreviewResolutionError",
    "PreviewResolver",
    "StartouchShadowExecutor",
    "load_preview_resolver",
]
