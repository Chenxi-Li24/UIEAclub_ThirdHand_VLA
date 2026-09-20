"""Content-addressed, tamper-evident recording of immutable RGB-D frames."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

import numpy as np

from thirdhand_va.common.contracts import RgbdFrame

_ARRAY_NAMES = ("rgb", "depth_m", "xyz_camera_m")
_SCHEMA = "thirdhand-va-rgbd-frame-v1"


class RecordingError(RuntimeError):
    """A frame bundle is incomplete, malformed, or fails its content hash."""


def _array_spec(array: np.ndarray) -> dict[str, Any]:
    return {"dtype": array.dtype.str, "shape": list(array.shape)}


def _metadata_core(frame: RgbdFrame) -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "sequence": frame.sequence,
        "monotonic_ns": frame.monotonic_ns,
        "camera_serial": frame.camera_serial,
        "arrays": {
            "rgb": _array_spec(frame.rgb),
            "depth_m": _array_spec(frame.depth_m),
            "xyz_camera_m": _array_spec(frame.xyz_camera_m),
        },
    }


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _content_id(
    metadata_core: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
) -> str:
    digest = hashlib.sha256()
    digest.update(_canonical_json(metadata_core))
    for name in _ARRAY_NAMES:
        array = np.ascontiguousarray(arrays[name])
        digest.update(name.encode("ascii") + b"\0")
        digest.update(memoryview(array).cast("B"))
    return f"sha256:{digest.hexdigest()}"


def write_frame_bundle(directory: str | Path, frame: RgbdFrame) -> str:
    """Write arrays first and atomically publish their hash-bearing manifest."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    arrays = {
        "rgb": np.asarray(frame.rgb),
        "depth_m": np.asarray(frame.depth_m),
        "xyz_camera_m": np.asarray(frame.xyz_camera_m),
    }
    core = _metadata_core(frame)
    content_id = _content_id(core, arrays)
    metadata = dict(core)
    metadata["content_id"] = content_id

    arrays_temp: Path | None = None
    metadata_temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target,
            prefix=".arrays-",
            suffix=".npz",
            delete=False,
        ) as stream:
            arrays_temp = Path(stream.name)
        np.savez_compressed(arrays_temp, **arrays)
        os.replace(arrays_temp, target / "arrays.npz")
        arrays_temp = None

        with tempfile.NamedTemporaryFile(
            dir=target,
            prefix=".metadata-",
            suffix=".json",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as stream:
            metadata_temp = Path(stream.name)
            json.dump(
                metadata,
                stream,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(metadata_temp, target / "metadata.json")
        metadata_temp = None
    finally:
        for temporary in (arrays_temp, metadata_temp):
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return content_id


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecordingError(f"content metadata cannot be read: {error}") from error
    if not isinstance(metadata, dict) or not isinstance(
        metadata.get("content_id"), str
    ):
        raise RecordingError("content metadata is missing content_id")
    return metadata


def read_frame_bundle(directory: str | Path) -> RgbdFrame:
    target = Path(directory)
    metadata = _load_metadata(target / "metadata.json")
    expected_id = metadata.pop("content_id")
    if metadata.get("schema") != _SCHEMA:
        raise RecordingError("content metadata has an unsupported schema")
    specs = metadata.get("arrays")
    if not isinstance(specs, dict) or set(specs) != set(_ARRAY_NAMES):
        raise RecordingError("content metadata has invalid array declarations")
    try:
        with np.load(target / "arrays.npz", allow_pickle=False) as stored:
            if set(stored.files) != set(_ARRAY_NAMES):
                raise RecordingError("content archive has unexpected arrays")
            arrays = {name: stored[name].copy() for name in _ARRAY_NAMES}
    except RecordingError:
        raise
    except (OSError, ValueError, KeyError) as error:
        raise RecordingError(f"content arrays cannot be read: {error}") from error

    for name, array in arrays.items():
        spec = specs[name]
        if (
            not isinstance(spec, dict)
            or spec.get("dtype") != array.dtype.str
            or spec.get("shape") != list(array.shape)
        ):
            raise RecordingError(f"content array {name} does not match metadata")
    actual_id = _content_id(metadata, arrays)
    if actual_id != expected_id:
        raise RecordingError(
            f"content hash mismatch: expected {expected_id}, got {actual_id}"
        )
    try:
        return RgbdFrame(
            sequence=int(metadata["sequence"]),
            monotonic_ns=int(metadata["monotonic_ns"]),
            camera_serial=str(metadata["camera_serial"]),
            rgb=arrays["rgb"],
            depth_m=arrays["depth_m"],
            xyz_camera_m=arrays["xyz_camera_m"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RecordingError(f"content metadata is invalid: {error}") from error
