import base64
import json
from pathlib import Path
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services/edge-agent/src"))
from thirdhand_edge.protocol import ProtocolError, verify_envelope
from thirdhand_edge.transport import DeviceConfig, create_tls_context


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def envelope(key, **overrides):
    payload = {"schema": 1, "purpose": "probe", "keyId": "test", "deviceId": "a", "bootId": "b", "executorEpoch": None, "connectionId": "c", "issuedAt": 1000, "expiresAt": 2000, **overrides}
    raw = json.dumps(payload).encode()
    return {"keyId": "test", "payloadBase64url": b64(raw), "signatureBase64url": b64(key.sign(raw))}


def test_signature_exact_bytes_and_bound_context():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    keys = {"test": public, "alias": public}
    binding = {"deviceId": "a", "bootId": "b", "executorEpoch": None, "connectionId": "c"}
    item = envelope(key)
    assert verify_envelope(item, keys, binding, now_ms=1500)["purpose"] == "probe"
    for changed in ({**item, "keyId": "alias"}, {**item, "payloadBase64url": b64(b"{}")}, {**item, "signatureBase64url": b64(b"0" * 64)}):
        with pytest.raises(ProtocolError):
            verify_envelope(changed, keys, binding, now_ms=1500)
    with pytest.raises(ProtocolError):
        verify_envelope(item, keys, {**binding, "deviceId": "other"}, now_ms=1500)
    with pytest.raises(ProtocolError):
        verify_envelope(item, keys, binding, now_ms=2000)


def test_probe_config_requires_wss_and_no_credentials_in_url(tmp_path):
    for url in ("ws://localhost/edge/v1/connect", "wss://user:password@localhost/edge/v1/connect", "wss://localhost/edge/v1/connect?token=secret"):
        with pytest.raises(ValueError):
            DeviceConfig(url=url, device_id="a", boot_id="b", certificate=tmp_path / "a", private_key=tmp_path / "b")


def test_import_probe_never_imports_hardware_or_sdk():
    import thirdhand_edge.transport as transport
    assert not hasattr(transport, "RobotClient")
    assert not any(name.startswith(("can", "RobotController", "cv2", "pyrealsense2")) for name in sys.modules)
