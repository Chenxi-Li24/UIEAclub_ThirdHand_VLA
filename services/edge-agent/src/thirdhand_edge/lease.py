"""Only signed lease messages can renew the independent Robot watchdog."""
import uuid

from .protocol import ProtocolError, verify_envelope


def verify_lease(envelope, trusted_keys, context, *, now_ms):
    payload = verify_envelope(envelope, trusted_keys, context, now_ms=now_ms)
    fields = {"schema", "keyId", "purpose", "deviceId", "bootId", "executorEpoch", "connectionId", "certificateId", "leaseId", "leaseEpoch", "sequence", "issuedAt", "expiresAt"}
    if set(payload) != fields or payload["purpose"] not in ("lease_grant", "lease_renew") or payload["certificateId"] != context["certificateId"] or payload["expiresAt"] - now_ms > 1000:
        raise ProtocolError("INVALID_LEASE")
    try:
        uuid.UUID(payload["leaseId"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProtocolError("INVALID_LEASE") from exc
    if type(payload["leaseEpoch"]) is not int or not 1 <= payload["leaseEpoch"] <= 9007199254740991 or type(payload["sequence"]) is not int or not 0 <= payload["sequence"] <= 9007199254740991:
        raise ProtocolError("INVALID_LEASE")
    return payload
