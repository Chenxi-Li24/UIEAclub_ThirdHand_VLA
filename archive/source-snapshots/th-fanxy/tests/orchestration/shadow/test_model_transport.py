import subprocess
import sys

import pytest
from pydantic import SecretStr, ValidationError

from uiea_thirdhand_vla.orchestration.shadow.model_transport import (
    AllowListedHttpTransport,
    DisabledTransport,
    HttpTransportConfig,
    InjectedTransport,
    ModelTransportDisabled,
    ModelTransportError,
)


def test_disabled_transport_rejects_every_request():
    with pytest.raises(ModelTransportDisabled, match="disabled"):
        DisabledTransport().request({"query": "is the bottle held?"})


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "endpoint": "http://models.example/v1/verify",
            "allowed_endpoints": ("http://models.example/v1/verify",),
        },
        {
            "endpoint": "https://models.example/v1/verify",
            "allowed_endpoints": ("https://other.example/v1/verify",),
        },
        {
            "endpoint": "https://models.example/v1/verify?debug=1",
            "allowed_endpoints": ("https://models.example/v1/verify?debug=1",),
        },
        {
            "endpoint": "https://models.example/v1/verify",
            "allowed_endpoints": ("https://models.example/v1/verify",),
            "timeout_s": 61.0,
        },
    ],
)
def test_http_config_rejects_unsafe_endpoint_or_timeout(kwargs):
    with pytest.raises(ValidationError):
        HttpTransportConfig(enabled=True, **kwargs)


def test_loopback_http_and_allowlisted_https_are_accepted():
    loopback = HttpTransportConfig(
        enabled=True,
        endpoint="http://127.0.0.1:8080/verify",
        allowed_endpoints=("http://127.0.0.1:8080/verify",),
    )
    secure = HttpTransportConfig(
        enabled=True,
        endpoint="https://models.example/v1/verify",
        allowed_endpoints=("https://models.example/v1/verify",),
    )

    assert loopback.enabled is True
    assert secure.enabled is True


def test_injected_transport_returns_real_validated_object():
    transport = InjectedTransport(
        lambda payload: {
            "verdict": "PASS",
            "query": payload["query"],
            "robot_execution_enabled": False,
        }
    )

    result = transport.request({"query": "is the bottle held?"})

    assert result == {
        "verdict": "PASS",
        "query": "is the bottle held?",
        "robot_execution_enabled": False,
    }


def test_injected_transport_rejects_non_object_or_nonfinite_output():
    with pytest.raises(ModelTransportError, match="JSON object"):
        InjectedTransport(lambda _payload: ["PASS"]).request({"query": "q"})
    with pytest.raises(ModelTransportError, match="finite JSON"):
        InjectedTransport(lambda _payload: {"score": float("nan")}).request(
            {"query": "q"}
        )


class BytesSender:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.requests: list[tuple[str, dict[str, str], dict[str, object], float, int]] = []

    def send(self, endpoint, headers, payload, timeout_s, max_response_bytes):
        self.requests.append((endpoint, headers, payload, timeout_s, max_response_bytes))
        return self.response


def test_allowlisted_http_transport_validates_response_and_redacts_secret():
    sender = BytesSender(b'{"verdict":"UNKNOWN","evidence_ids":[]}')
    config = HttpTransportConfig(
        enabled=True,
        endpoint="https://models.example/v1/verify",
        allowed_endpoints=("https://models.example/v1/verify",),
        timeout_s=3.0,
        api_key=SecretStr("super-secret"),
    )
    transport = AllowListedHttpTransport(config, sender=sender)

    result = transport.request({"query": "handoff ready?"})

    assert result == {"verdict": "UNKNOWN", "evidence_ids": []}
    endpoint, headers, request_payload, timeout_s, max_bytes = sender.requests[0]
    assert endpoint == "https://models.example/v1/verify"
    assert headers["Authorization"] == "Bearer super-secret"
    assert request_payload == {"query": "handoff ready?"}
    assert timeout_s == 3.0
    assert max_bytes == 1024 * 1024
    audit = transport.audit_metadata()
    assert audit == {
        "enabled": True,
        "endpoint": "https://models.example/v1/verify",
        "has_api_key": True,
        "max_response_bytes": 1024 * 1024,
        "timeout_s": 3.0,
    }
    assert "super-secret" not in repr(config)
    assert "super-secret" not in repr(audit)


def test_http_transport_rejects_oversized_or_non_object_response():
    config = HttpTransportConfig(
        enabled=True,
        endpoint="http://localhost:8080/verify",
        allowed_endpoints=("http://localhost:8080/verify",),
        max_response_bytes=32,
    )

    with pytest.raises(ModelTransportError, match="exceeds"):
        AllowListedHttpTransport(config, sender=BytesSender(b"x" * 33)).request({})
    with pytest.raises(ModelTransportError, match="JSON object"):
        AllowListedHttpTransport(config, sender=BytesSender(b"[]")).request({})


def test_http_transport_module_does_not_import_httpx_until_request():
    code = """
import sys

class BlockHttpx:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "httpx":
            raise ImportError("httpx import blocked")
        return None

sys.meta_path.insert(0, BlockHttpx())
from uiea_thirdhand_vla.orchestration.shadow.model_transport import HttpTransportConfig
print(HttpTransportConfig.__name__)
"""

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "HttpTransportConfig"
