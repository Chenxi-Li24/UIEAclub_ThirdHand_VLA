"""Signed UTF-8 bytes are verified before JSON is parsed."""
import base64
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class ProtocolError(ValueError):
    pass


def decode_b64(value, maximum=16384):
    if not isinstance(value, str) or not 0 < len(value) <= maximum or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ProtocolError("INVALID_ENCODING")
    data = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if base64.urlsafe_b64encode(data).decode().rstrip("=") != value:
        raise ProtocolError("INVALID_ENCODING")
    return data


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolError("DUPLICATE_KEY")
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("NONFINITE_NUMBER")))
    except (ValueError, UnicodeError) as exc:
        raise ProtocolError("INVALID_JSON") from exc


def verify_envelope(envelope, trusted_keys, context, *, now_ms):
    if not isinstance(envelope, dict) or set(envelope) != {"keyId", "payloadBase64url", "signatureBase64url"}:
        raise ProtocolError("INVALID_ENVELOPE")
    key_id = envelope["keyId"]
    if not isinstance(key_id, str) or key_id not in trusted_keys:
        raise ProtocolError("UNKNOWN_KEY")
    raw = decode_b64(envelope["payloadBase64url"])
    signature = decode_b64(envelope["signatureBase64url"], 86)
    try:
        key = serialization.load_pem_public_key(trusted_keys[key_id].encode() if isinstance(trusted_keys[key_id], str) else trusted_keys[key_id])
        if not isinstance(key, Ed25519PublicKey) or len(signature) != 64:
            raise ProtocolError("INVALID_KEY")
        key.verify(signature, raw)
    except (ValueError, InvalidSignature) as exc:
        raise ProtocolError("INVALID_SIGNATURE") from exc
    payload = parse_json(raw)
    if not isinstance(payload, dict) or payload.get("keyId") != key_id or type(payload.get("schema")) is not int or payload["schema"] != 1:
        raise ProtocolError("INVALID_PAYLOAD")
    for field in ("deviceId", "bootId", "executorEpoch", "connectionId"):
        if field not in context or field not in payload or payload[field] != context[field]:
            raise ProtocolError("WRONG_CONTEXT")
    if "certificateId" in context and payload.get("certificateId") != context["certificateId"]:
        raise ProtocolError("WRONG_CONTEXT")
    issued, expires = payload.get("issuedAt"), payload.get("expiresAt")
    if type(issued) is not int or type(expires) is not int or issued > now_ms + 500 or expires <= now_ms or not 0 < expires - issued <= 5000:
        raise ProtocolError("EXPIRED_ENVELOPE")
    return payload
