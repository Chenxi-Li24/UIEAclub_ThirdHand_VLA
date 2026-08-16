from __future__ import annotations

import http.client
import importlib.util
import json
import threading
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "web-control" / "server" / "startouch_execution_service.py"
ADAPTER_TEST_PATH = ROOT / "tests" / "control" / "test_startouch_fixed_waypoint_adapter.py"

SERVICE_SPEC = importlib.util.spec_from_file_location("startouch_execution_service", SERVICE_PATH)
assert SERVICE_SPEC and SERVICE_SPEC.loader
service = importlib.util.module_from_spec(SERVICE_SPEC)
SERVICE_SPEC.loader.exec_module(service)

REQUEST_SPEC = importlib.util.spec_from_file_location("adapter_test_fixtures", ADAPTER_TEST_PATH)
assert REQUEST_SPEC and REQUEST_SPEC.loader
request_fixtures = importlib.util.module_from_spec(REQUEST_SPEC)
REQUEST_SPEC.loader.exec_module(request_fixtures)


def _serve(binding_file: Path | None = None):
    server = service.create_server(port=0, binding_file=binding_file)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    return server, thread


def _request(server, method: str, path: str, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = dict(headers or {})
    if encoded is not None:
        request_headers.setdefault("Content-Type", "application/json")
        request_headers.setdefault("Content-Length", str(len(encoded)))
    connection.request(method, path, body=encoded, headers=request_headers)
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, payload


def _stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    assert not thread.is_alive()


def test_health_is_loopback_read_only_and_reports_no_hardware_access():
    server, thread = _serve()
    try:
        status, payload = _request(server, "GET", "/health")
    finally:
        _stop(server, thread)
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["realModeEnabled"] is False
    assert payload["hardwareAccess"] is False
    assert payload["bridgeStarted"] is False
    assert payload["sdkInitialized"] is False
    assert payload["canOpened"] is False
    assert payload["motionCommandsEnabled"] is False


def test_http_simulate_and_dry_run_contract_results():
    server, thread = _serve()
    try:
        simulate = request_fixtures.execution_request()
        simulate_status, simulate_result = _request(
            server, "POST", "/v1/execution", simulate
        )
        dry_run = deepcopy(simulate)
        dry_run["messageId"] = "msg-control-dry-run"
        dry_run["mode"] = "dry-run"
        dry_status, dry_result = _request(server, "POST", "/v1/execution", dry_run)
    finally:
        _stop(server, thread)
    assert simulate_status == 200
    assert simulate_result["status"] == "success"
    assert simulate_result["payload"]["executedSteps"] == 11
    assert dry_status == 200
    assert dry_result["status"] == "success"
    assert dry_result["payload"]["executedSteps"] == 0
    for result in (simulate_result, dry_result):
        assert result["payload"]["hardwareFeedbackVerified"] is False
        assert result["payload"]["bridgeEvidence"]["commandCompleteCount"] == 0


def test_http_rejects_invalid_json_as_schema_valid_service_error():
    server, thread = _serve()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        body = b'{"mode":"simulate","mode":"real"}'
        connection.request(
            "POST",
            "/v1/execution",
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
    finally:
        _stop(server, thread)
    assert response.status == 400
    assert payload["type"] == "service.error"
    assert payload["status"] == "failure"
    assert payload["payload"] == {"stage": "execution"}
    assert payload["error"]["code"] == "invalid_json"
    service.adapter._validate_contract_message(
        service.adapter._contract_validator(ROOT), payload, "service.error"
    )


def test_http_identity_binding_blocks_mismatch(tmp_path):
    request = request_fixtures.execution_request()
    binding = {
        request["sessionId"]: {
            "traceId": request["traceId"],
            "candidateId": request["payload"]["candidateId"],
            "decisionId": request["payload"]["decisionId"],
            "targetId": "different-target",
        }
    }
    binding_file = tmp_path / "bindings.json"
    binding_file.write_text(json.dumps(binding), encoding="utf-8")
    server, thread = _serve(binding_file)
    try:
        status, result = _request(server, "POST", "/v1/execution", request)
    finally:
        _stop(server, thread)
    assert status == 200
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "identity_mismatch"


def test_invalid_identity_binding_is_a_service_configuration_failure(tmp_path):
    binding_file = tmp_path / "bindings.json"
    binding_file.write_text('{"session":{},"session":{}}', encoding="utf-8")
    server, thread = _serve(binding_file)
    try:
        status, result = _request(
            server,
            "POST",
            "/v1/execution",
            request_fixtures.execution_request(),
        )
    finally:
        _stop(server, thread)
    assert status == 503
    assert result["type"] == "service.error"
    assert result["payload"] == {"stage": "execution"}
    assert result["error"]["code"] == "identity_binding_unavailable"


def test_unsupported_http_method_returns_json_service_error():
    server, thread = _serve()
    try:
        status, result = _request(server, "PUT", "/v1/execution")
    finally:
        _stop(server, thread)
    assert status == 501
    assert result["type"] == "service.error"
    assert result["payload"] == {"stage": "execution"}
    assert result["error"]["code"] == "http_protocol_error"


def test_concurrent_request_is_blocked_without_entering_adapter_twice():
    server, thread = _serve()
    entered = threading.Event()
    release = threading.Event()
    original = service.adapter.process_execution_request
    call_count = 0
    call_lock = threading.Lock()

    def slow_process(*args, **kwargs):
        nonlocal call_count
        with call_lock:
            call_count += 1
        entered.set()
        assert release.wait(timeout=3)
        return original(*args, **kwargs)

    first_result = {}

    def first_call():
        first_result["response"] = _request(
            server,
            "POST",
            "/v1/execution",
            request_fixtures.execution_request(),
        )

    with patch.object(service.adapter, "process_execution_request", side_effect=slow_process):
        first_thread = threading.Thread(target=first_call)
        first_thread.start()
        assert entered.wait(timeout=3)
        second_request = request_fixtures.execution_request()
        second_request["messageId"] = "msg-control-concurrent"
        second_status, second_result = _request(
            server, "POST", "/v1/execution", second_request
        )
        release.set()
        first_thread.join(timeout=3)
    _stop(server, thread)

    assert first_result["response"][0] == 200
    assert first_result["response"][1]["status"] == "success"
    assert second_status == 409
    assert second_result["status"] == "blocked"
    assert second_result["error"]["code"] == "concurrent_execution_blocked"
    assert second_result["payload"]["executedSteps"] == 0
    assert call_count == 1


def test_service_refuses_non_loopback_binding():
    try:
        service.create_server(host="0.0.0.0", port=7788)
    except ValueError as exc:
        assert "loopback-only" in str(exc)
    else:
        raise AssertionError("service accepted a non-loopback bind")
