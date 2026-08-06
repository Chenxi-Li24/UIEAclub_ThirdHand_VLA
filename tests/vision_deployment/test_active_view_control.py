from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT_DIR = ROOT / "scripts/vision"
SCRIPT = SCRIPT_DIR / "verify_active_view_control.py"
sys.path.insert(0, str(SCRIPT_DIR))

from verify_active_view_control import (  # noqa: E402
    ActiveViewControlEvidenceError,
    evaluate_active_view_control,
    simulated_success_events,
)

EVIDENCE_ID = f"sha256:{'a' * 64}"


def success_events():
    return [dict(event) for event in simulated_success_events(EVIDENCE_ID, duration_seconds=30)]


def first_index(events, event_type):
    return next(index for index, event in enumerate(events) if event["type"] == event_type)


def replace_tail(events, event_type, **changes):
    index = first_index(events, event_type)
    events[index].update(changes)
    del events[index + 1 :]


def end_before(events, before_type, event_type):
    index = first_index(events, before_type)
    timestamp = events[index - 1]["ts_ms"] + 1
    del events[index:]
    events.append({"type": event_type, "ts_ms": timestamp})


def test_simulated_session_reaches_grasp_preview_without_grasp_command():
    report = evaluate_active_view_control(success_events(), EVIDENCE_ID)

    assert report["passed"] is True
    assert report["session_count"] == 1
    assert report["observation_moves"] == 2
    assert report["grasp_commands"] == 0
    assert report["max_translation_m"] <= 0.020
    assert report["commands_after_abort"] == 0
    assert report["identity_confirmations"] == 4
    assert report["depth_samples"] >= 5
    assert report["execution_gate_violations"] == 0


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda events: replace_tail(events, "identity_observed", identity_id=99), "identity"),
        (lambda events: replace_tail(events, "depth_observed", fresh=False), "stale"),
        (
            lambda events: replace_tail(
                events,
                "motion_completed",
                request_id="99999999-9999-4999-8999-999999999999"
            ),
            "request",
        ),
        (lambda events: end_before(events, "motion_started", "disconnect"), "disconnect"),
        (
            lambda events: end_before(events, "motion_started", "approval_expired"),
            "approval",
        ),
        (
            lambda events: replace_tail(
                events,
                "proposal",
                evidence_ids=[f"sha256:{'b' * 64}"]
            ),
            "evidence",
        ),
        (
            lambda events: replace_tail(events, "operator_confirmed", ts_ms=201),
            "stale proposal",
        ),
        (
            lambda events: end_before(events, "motion_completed", "motion_timeout"),
            "motion timeout",
        ),
        (
            lambda events: replace_tail(events, "identity_observed", confirmed=False),
            "ambiguous",
        ),
        (
            lambda events: end_before(events, "motion_started", "d435_disconnected"),
            "d435",
        ),
        (
            lambda events: end_before(events, "motion_started", "evidence_expired"),
            "evidence",
        ),
    ],
)
def test_faults_abort_without_followup_motion(mutation, reason):
    events = success_events()
    mutation(events)

    report = evaluate_active_view_control(events, EVIDENCE_ID)

    assert report["passed"] is False
    assert reason in "\n".join(report["errors"]).lower()
    assert report["commands_after_abort"] == 0


def test_motion_after_abort_and_grasp_commands_are_counted_and_rejected():
    events = success_events()
    proposal_index = first_index(events, "proposal")
    events[proposal_index + 1 :] = [
        {"type": "d435_disconnected", "ts_ms": 12},
        {
            "type": "motion_started",
            "ts_ms": 13,
            "session_id": events[0]["session_id"],
            "proposal_id": events[proposal_index]["proposal_id"],
            "request_id": "33333333-3333-4333-8333-333333333333",
            "simulated": True,
        },
        {"type": "robot_command", "ts_ms": 14, "cmd": "grasp"},
    ]

    report = evaluate_active_view_control(events, EVIDENCE_ID)

    assert report["passed"] is False
    assert report["commands_after_abort"] == 2
    assert report["grasp_commands"] == 1


def test_control_evaluator_rejects_nonfinite_unbounded_or_invalid_evidence():
    events = success_events()
    events[first_index(events, "proposal")]["delta_base_m"] = [float("nan"), 0, 0]
    with pytest.raises(ActiveViewControlEvidenceError, match="finite"):
        evaluate_active_view_control(events, EVIDENCE_ID)

    with pytest.raises(ActiveViewControlEvidenceError, match="100,000"):
        evaluate_active_view_control([{"type": "noop"}] * 100_001, EVIDENCE_ID)

    with pytest.raises(ActiveViewControlEvidenceError, match="evidence"):
        evaluate_active_view_control([], "not-an-evidence-id")


def test_cli_runs_a_virtual_30_minute_soak_without_sleeping(tmp_path: Path):
    output = tmp_path / "active-view-control.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base-url",
            "http://127.0.0.1:9",
            "--duration-seconds",
            "1800",
            "--output",
            str(output),
            "--expected-evidence-id",
            EVIDENCE_ID,
            "--simulation-only",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["simulation_only"] is True
    assert report["virtual_duration_seconds"] == 1800
    assert report["session_count"] == 60
    assert report["completed_sessions"] == 60
    assert report["observation_moves"] == 120
    assert report["grasp_commands"] == 0
    assert report["unexpected_transitions"] == 0
    assert report["stale_accepted_proposals"] == 0
