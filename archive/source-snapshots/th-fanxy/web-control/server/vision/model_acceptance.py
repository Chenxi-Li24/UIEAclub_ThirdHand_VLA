"""Content-addressed task-model acceptance for execution gating."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


MAX_ACCEPTANCE_BYTES = 8 * 1024 * 1024
CRITERIA = {
    "min_id_continuity": 0.90,
    "min_positive_objects": 10,
    "min_precision": 0.90,
    "min_recall": 0.90,
    "min_samples": 10,
}


class ModelAcceptanceError(ValueError):
    """Raised when task-model evidence is missing, stale, or malformed."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ModelAcceptanceError("acceptance evidence must be finite JSON") from exc


def _content_id(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _file_hash(path: Path | str, label: str) -> str:
    source = Path(path).resolve()
    if not source.is_file() or source.is_symlink():
        raise ModelAcceptanceError(f"{label} must be a regular local file")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load(path: Path | str, label: str) -> Mapping[str, Any]:
    source = Path(path).resolve()
    if not source.is_file() or source.is_symlink():
        raise ModelAcceptanceError(f"{label} must be a regular local file")
    if source.stat().st_size > MAX_ACCEPTANCE_BYTES:
        raise ModelAcceptanceError(f"{label} exceeds 8 MiB")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelAcceptanceError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ModelAcceptanceError(f"{label} must be an object")
    _canonical(value)
    return value


def _labels(value: Any, name: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ModelAcceptanceError(f"{name} must contain unique non-empty labels")
    return tuple(value)


def _timestamp(value: Any) -> str:
    if not isinstance(value, str):
        raise ModelAcceptanceError("manifest created_at must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelAcceptanceError("manifest created_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ModelAcceptanceError("manifest created_at requires a timezone")
    return value


def _metrics(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    if set(manifest) != {"schema_version", "created_at", "label_scope", "samples"}:
        raise ModelAcceptanceError("dataset manifest keys are invalid")
    if manifest["schema_version"] != 1:
        raise ModelAcceptanceError("dataset manifest schema is unsupported")
    _timestamp(manifest["created_at"])
    scope = set(_labels(manifest["label_scope"], "label_scope"))
    samples = manifest["samples"]
    if not isinstance(samples, list) or not samples:
        raise ModelAcceptanceError("dataset samples must be a non-empty list")

    true_positive = 0
    false_positive = 0
    false_negative = 0
    positive_objects = 0
    identities: dict[str, list[int]] = defaultdict(list)
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict) or set(sample) != {
            "image_sha256", "expected_objects", "predictions"
        }:
            raise ModelAcceptanceError(f"samples[{index}] keys are invalid")
        image_id = sample["image_sha256"]
        if (
            not isinstance(image_id, str)
            or not image_id.startswith("sha256:")
            or len(image_id) != 71
        ):
            raise ModelAcceptanceError(f"samples[{index}] image hash is invalid")
        expected = sample["expected_objects"]
        predicted = sample["predictions"]
        if not isinstance(expected, list) or not isinstance(predicted, list):
            raise ModelAcceptanceError(f"samples[{index}] object lists are invalid")
        expected_by_id: dict[str, str] = {}
        for item in expected:
            if not isinstance(item, dict) or set(item) != {"object_id", "label"}:
                raise ModelAcceptanceError(f"samples[{index}] expected object is invalid")
            object_id, label = item["object_id"], item["label"]
            if (
                not isinstance(object_id, str)
                or not object_id
                or label not in scope
                or object_id in expected_by_id
            ):
                raise ModelAcceptanceError(f"samples[{index}] expected object is invalid")
            expected_by_id[object_id] = label
        positive_objects += len(expected_by_id)
        matched: set[str] = set()
        for item in predicted:
            if not isinstance(item, dict) or set(item) != {
                "identity_id", "label", "matched_object_id"
            }:
                raise ModelAcceptanceError(f"samples[{index}] prediction is invalid")
            identity_id = item["identity_id"]
            label = item["label"]
            object_id = item["matched_object_id"]
            if isinstance(identity_id, bool) or not isinstance(identity_id, int) or identity_id < 1:
                raise ModelAcceptanceError(f"samples[{index}] identity ID is invalid")
            valid_match = (
                label in scope
                and object_id in expected_by_id
                and expected_by_id[object_id] == label
                and object_id not in matched
            )
            if valid_match:
                matched.add(object_id)
                identities[object_id].append(identity_id)
                true_positive += 1
            elif label in scope:
                false_positive += 1
        false_negative += len(expected_by_id) - len(matched)

    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    continuity_scores = [
        Counter(values).most_common(1)[0][1] / len(values)
        for values in identities.values()
        if values
    ]
    continuity = sum(continuity_scores) / max(1, len(continuity_scores))
    metrics = {
        "false_negatives": false_negative,
        "false_positives": false_positive,
        "id_continuity": continuity,
        "positive_objects": positive_objects,
        "precision": precision,
        "recall": recall,
        "sample_count": len(samples),
        "true_positives": true_positive,
    }
    failures = []
    for metric, criterion in (
        ("sample_count", "min_samples"),
        ("positive_objects", "min_positive_objects"),
        ("precision", "min_precision"),
        ("recall", "min_recall"),
        ("id_continuity", "min_id_continuity"),
    ):
        value = metrics[metric]
        minimum = CRITERIA[criterion]
        if not math.isfinite(float(value)) or value < minimum:
            failures.append(f"{metric}_below_threshold")
    return metrics, tuple(failures)


def evaluate_task_checkpoint(
    manifest_path: Path | str,
    *,
    detector_config_path: Path | str,
    detector_checkpoint_path: Path | str,
    descriptor_model_id: str,
    output_path: Path | str,
) -> dict[str, Any]:
    """Evaluate a controlled labeled set and atomically write acceptance evidence."""

    if not isinstance(descriptor_model_id, str) or not descriptor_model_id:
        raise ModelAcceptanceError("descriptor model ID is invalid")
    manifest = _load(manifest_path, "dataset manifest")
    metrics, failures = _metrics(manifest)
    payload = {
        "accepted_labels": list(_labels(manifest["label_scope"], "label_scope")),
        "created_at": _timestamp(manifest["created_at"]),
        "criteria": dict(CRITERIA),
        "dataset_manifest_sha256": _file_hash(manifest_path, "dataset manifest"),
        "failure_reasons": list(failures),
        "metrics": metrics,
        "model": {
            "descriptor_model_id": descriptor_model_id,
            "detector_checkpoint_sha256": _file_hash(
                detector_checkpoint_path, "detector checkpoint"
            ),
            "detector_config_sha256": _file_hash(
                detector_config_path, "detector config"
            ),
        },
        "schema_version": 1,
        "validated": not failures,
    }
    evidence = {**payload, "content_id": _content_id(payload)}
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(_canonical(evidence) + "\n", encoding="utf-8")
    temporary.replace(output)
    return evidence


def validate_task_checkpoint(
    evidence_path: Path | str,
    *,
    detector_config_path: Path | str,
    detector_checkpoint_path: Path | str,
    descriptor_model_id: str,
    requested_labels: Iterable[str],
) -> tuple[str, ...]:
    """Bind acceptance evidence to exact local models and requested label scope."""

    evidence = _load(evidence_path, "model acceptance evidence")
    supplied_id = evidence.get("content_id")
    payload = dict(evidence)
    payload.pop("content_id", None)
    if supplied_id != _content_id(payload):
        raise ModelAcceptanceError("model acceptance integrity check failed")
    if payload.get("schema_version") != 1 or payload.get("validated") is not True:
        raise ModelAcceptanceError("model acceptance is not validated")
    if payload.get("failure_reasons") != [] or payload.get("criteria") != CRITERIA:
        raise ModelAcceptanceError("model acceptance criteria are invalid")
    model = payload.get("model")
    if not isinstance(model, dict):
        raise ModelAcceptanceError("model acceptance model record is invalid")
    if model.get("detector_config_sha256") != _file_hash(
        detector_config_path, "detector config"
    ):
        raise ModelAcceptanceError("detector config hash does not match acceptance")
    if model.get("detector_checkpoint_sha256") != _file_hash(
        detector_checkpoint_path, "detector checkpoint"
    ):
        raise ModelAcceptanceError("detector checkpoint hash does not match acceptance")
    if model.get("descriptor_model_id") != descriptor_model_id:
        raise ModelAcceptanceError("descriptor model ID does not match acceptance")
    accepted = _labels(payload.get("accepted_labels"), "accepted_labels")
    requested = tuple(requested_labels)
    if not requested or any(label not in accepted for label in requested):
        raise ModelAcceptanceError("requested label is outside accepted scope")
    return tuple(label for label in accepted if label in requested)


__all__ = [
    "ModelAcceptanceError",
    "evaluate_task_checkpoint",
    "validate_task_checkpoint",
]
