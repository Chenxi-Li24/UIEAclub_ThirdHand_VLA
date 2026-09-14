"""
Load and validate messages against ``contracts/schema.json``.

``jsonschema`` is used when available and falls back to a small dependency-free
runtime check so the service still rejects obviously-bad messages on hosts that
do not install the optional package.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"

try:
    from jsonschema import Draft202012Validator  # type: ignore
except ImportError:  # pragma: no cover - optional package
    Draft202012Validator = None

_validator = None


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _get_validator():
    global _validator
    if _validator is None and Draft202012Validator is not None:
        _validator = Draft202012Validator(load_schema())
    return _validator


def validate_message(message: dict) -> list[str]:
    """Return a list of schema violations (empty when the message is valid)."""
    errors: list[str] = []

    validator = _get_validator()
    if validator is not None:
        for error in validator.iter_errors(message):
            path = "/".join(str(part) for part in error.absolute_path) or "(root)"
            errors.append(f"{path}: {error.message}")
        return errors

    # Dependency-free fallback: enforce the base message envelope.
    required = {
        "schemaVersion", "type", "messageId", "replyTo", "sessionId",
        "traceId", "ts", "source", "target", "mode", "payload",
    }
    missing = required - set(message)
    if missing:
        errors.append(f"missing base fields: {sorted(missing)}")
    if message.get("schemaVersion") != "1.0":
        errors.append("schemaVersion must be '1.0'")
    if not isinstance(message.get("traceId"), str) or not message.get("traceId"):
        errors.append("traceId is required")
    return errors
