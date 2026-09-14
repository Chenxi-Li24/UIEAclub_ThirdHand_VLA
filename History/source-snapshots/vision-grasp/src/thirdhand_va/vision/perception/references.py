"""Content-addressed appearance descriptors for the one fixed experiment bottle."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable

import numpy as np
from numpy.typing import NDArray

_SCHEMA = "thirdhand-va-fixed-bottle-reference-v1"


class ReferenceError(RuntimeError):
    """The fixed-object reference set is missing or internally inconsistent."""


def _normalized(value: object) -> NDArray[np.float32]:
    descriptor = np.asarray(value, dtype=np.float32)
    if (
        descriptor.ndim != 1
        or descriptor.size == 0
        or not np.isfinite(descriptor).all()
    ):
        raise ReferenceError("reference descriptor must be a finite vector")
    norm = float(np.linalg.norm(descriptor))
    if norm <= 1e-12:
        raise ReferenceError("reference descriptor must have non-zero norm")
    result = np.array(descriptor / norm, dtype=np.float32, copy=True)
    result.setflags(write=False)
    return result


def _stored_descriptor(value: object) -> NDArray[np.float32]:
    descriptor = np.asarray(value, dtype=np.float32)
    if (
        descriptor.ndim != 1
        or descriptor.size == 0
        or not np.isfinite(descriptor).all()
    ):
        raise ReferenceError("reference descriptor must be a finite vector")
    return np.ascontiguousarray(descriptor)


def _descriptor_id(descriptor: NDArray[np.float32]) -> str:
    digest = hashlib.sha256()
    digest.update(b"thirdhand-va-reference-v1\0")
    digest.update(memoryview(np.ascontiguousarray(descriptor)).cast("B"))
    return f"sha256:{digest.hexdigest()}"


class ReferenceBank:
    def __init__(self, descriptors: Iterable[object]) -> None:
        normalized = tuple(_normalized(item) for item in descriptors)
        dimensions = {item.size for item in normalized}
        if len(dimensions) > 1:
            raise ReferenceError("reference descriptor dimensions do not match")
        self._descriptors = normalized

    @classmethod
    def empty(cls) -> "ReferenceBank":
        return cls(())

    @classmethod
    def from_descriptors(cls, descriptors: Iterable[object]) -> "ReferenceBank":
        return cls(descriptors)

    @classmethod
    def from_manifest(cls, path: str | Path) -> "ReferenceBank":
        try:
            manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReferenceError(f"reference content cannot be read: {error}") from error
        if not isinstance(manifest, dict) or manifest.get("schema") != _SCHEMA:
            raise ReferenceError("reference content has an unsupported schema")
        entries = manifest.get("entries")
        if not isinstance(entries, list):
            raise ReferenceError("reference content entries are missing")
        descriptors = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ReferenceError(f"reference content entry {index} is invalid")
            stored = _stored_descriptor(entry.get("descriptor"))
            if entry.get("content_id") != _descriptor_id(stored):
                raise ReferenceError(
                    f"reference content hash mismatch at entry {index}"
                )
            descriptors.append(_normalized(stored))
        return cls(descriptors)

    @classmethod
    def write_manifest(
        cls,
        path: str | Path,
        descriptors: Iterable[object],
    ) -> "ReferenceBank":
        bank = cls(descriptors)
        manifest = {
            "schema": _SCHEMA,
            "entries": [
                {
                    "content_id": _descriptor_id(descriptor),
                    "descriptor": [float(value) for value in descriptor],
                }
                for descriptor in bank._descriptors
            ],
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=f".{target.name}-",
                mode="w",
                encoding="utf-8",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(
                    manifest,
                    stream,
                    ensure_ascii=True,
                    indent=2,
                    sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return bank

    def __len__(self) -> int:
        return len(self._descriptors)

    @property
    def descriptors(self) -> tuple[NDArray[np.float32], ...]:
        return self._descriptors

    def max_similarity(self, descriptor: object) -> float | None:
        if not self._descriptors:
            return None
        query = _normalized(descriptor)
        if query.size != self._descriptors[0].size:
            raise ReferenceError("reference descriptor dimension mismatch")
        return max(float(np.dot(query, item)) for item in self._descriptors)
