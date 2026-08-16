from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "part_d_execution_handoff"
EXAMPLES = HANDOFF / "examples"
ADAPTER_PATH = ROOT / "web-control" / "scripts" / "startouch_fixed_waypoint_adapter.py"

SPEC = importlib.util.spec_from_file_location("part_d_handoff_adapter", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


REQUIRED_FILES = (
    HANDOFF / "DELIVERY.md",
    HANDOFF / "delivery_manifest.json",
    EXAMPLES / "execution_request_simulate.json",
    EXAMPLES / "execution_result_simulate.json",
    EXAMPLES / "execution_request_dry_run.json",
    EXAMPLES / "execution_result_dry_run.json",
    EXAMPLES / "execution_request_unconfirmed.json",
    EXAMPLES / "execution_result_blocked_unconfirmed.json",
    EXAMPLES / "execution_request_unsupported_plan.json",
    EXAMPLES / "execution_result_blocked_unsupported_plan.json",
    EXAMPLES / "execution_result_bridge_failure.json",
    HANDOFF / "evidence" / "test_report.md",
    HANDOFF / "evidence" / "simulate_smoke_test.log",
    HANDOFF / "evidence" / "dry_run_smoke_test.log",
)


def _load(name: str):
    return adapter.loads_json_strict((EXAMPLES / name).read_text(encoding="utf-8"))


def test_required_handoff_files_exist():
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.is_file()]
    assert not missing, f"missing handoff files: {missing}"


def test_every_handoff_json_has_no_duplicate_keys():
    for path in HANDOFF.rglob("*.json"):
        adapter.loads_json_strict(path.read_text(encoding="utf-8"))


def test_positive_requests_and_all_results_pass_shared_schema():
    validator = adapter._contract_validator(ROOT)
    contract_messages = (
        "execution_request_simulate.json",
        "execution_result_simulate.json",
        "execution_request_dry_run.json",
        "execution_result_dry_run.json",
        "execution_request_unsupported_plan.json",
        "execution_result_blocked_unsupported_plan.json",
        "execution_result_blocked_unconfirmed.json",
        "execution_result_bridge_failure.json",
    )
    for name in contract_messages:
        adapter._validate_contract_message(validator, _load(name), name)


def test_unconfirmed_request_is_intentionally_schema_invalid_negative_fixture():
    validator = adapter._contract_validator(ROOT)
    errors = list(validator.iter_errors(_load("execution_request_unconfirmed.json")))
    assert errors, "confirmed=false must be rejected by the shared Schema"


def test_replay_examples_match_adapter_fail_closed_semantics():
    simulate = _load("execution_request_simulate.json")
    dry_run = _load("execution_request_dry_run.json")
    unconfirmed = _load("execution_request_unconfirmed.json")
    unsupported = _load("execution_request_unsupported_plan.json")

    simulate_result = adapter.process_execution_request(simulate, root=ROOT)
    dry_run_result = adapter.process_execution_request(dry_run, root=ROOT)
    unconfirmed_result = adapter.process_execution_request(unconfirmed, root=ROOT)
    unsupported_result = adapter.process_execution_request(unsupported, root=ROOT)

    assert simulate_result["status"] == "success"
    assert simulate_result["payload"]["executedSteps"] == 11
    assert dry_run_result["status"] == "success"
    assert dry_run_result["payload"]["executedSteps"] == 0
    assert unconfirmed_result["status"] == "blocked"
    assert unconfirmed_result["payload"]["executedSteps"] == 0
    assert unsupported_result["status"] == "blocked"
    assert unsupported_result["error"]["code"] == "action_chunk_adapter_unavailable"
    for request, result in (
        (simulate, simulate_result),
        (dry_run, dry_run_result),
        (unconfirmed, unconfirmed_result),
        (unsupported, unsupported_result),
    ):
        assert result["replyTo"] == request["messageId"]
        assert result["sessionId"] == request["sessionId"]
        assert result["traceId"] == request["traceId"]
        assert result["mode"] == request["mode"]
        assert result["payload"]["candidateId"] == request["payload"]["candidateId"]
        assert result["payload"]["sequenceId"] == request["payload"]["executionPlan"]["planId"]
        assert result["payload"]["hardwareFeedbackVerified"] is False
        assert result["payload"]["bridgeEvidence"]["commandCompleteCount"] == 0


def test_checked_in_result_pairs_preserve_request_identity():
    pairs = (
        ("execution_request_simulate.json", "execution_result_simulate.json"),
        ("execution_request_dry_run.json", "execution_result_dry_run.json"),
        (
            "execution_request_unconfirmed.json",
            "execution_result_blocked_unconfirmed.json",
        ),
        (
            "execution_request_unsupported_plan.json",
            "execution_result_blocked_unsupported_plan.json",
        ),
    )
    for request_name, result_name in pairs:
        request = _load(request_name)
        result = _load(result_name)
        assert result["messageId"] != request["messageId"]
        assert result["replyTo"] == request["messageId"]
        assert result["sessionId"] == request["sessionId"]
        assert result["traceId"] == request["traceId"]
        assert result["mode"] == request["mode"]
        assert result["payload"]["candidateId"] == request["payload"]["candidateId"]
        assert result["payload"]["sequenceId"] == request["payload"]["executionPlan"]["planId"]
