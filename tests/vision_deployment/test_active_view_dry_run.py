from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import time


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/vision/verify_active_view_dry_run.py"
LAUNCHER = ROOT / "scripts/vision/start_dual_camera_online.sh"


def load_verifier():
    spec = importlib.util.spec_from_file_location("active_view_dry_run_verifier", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def healthy_status(lumos: int = 10, d435: int = 20) -> dict:
    return {
        "online": True,
        "modelReady": True,
        "d435Ready": True,
        "lumosReady": True,
        "roles": {
            "canonicalRgb": "lumos_rgb",
            "metricDepth": "d435_depth",
        },
        "sequences": {"lumos": lumos, "d435": d435},
        "sourceAgeMs": 100,
        "stale": False,
        "robotExecutionEnabled": False,
        "blockers": ["calibration_unavailable"],
        "activeView": {
            "executionEnabled": False,
            "reports": [{
                "detectionId": 7,
                "identityId": 3,
                "kind": "none",
                "targetPoseId": None,
                "expiresNs": None,
                "coarseCenterXYM": None,
                "validDepthPoints": 0,
                "centralFraction": None,
                "depthAcceptable": False,
                "stableSamples": 0,
                "remainingRefinements": 3,
                "reasons": ["calibration_unavailable"],
                "executionEnabled": False,
            }],
        },
    }


def test_verifier_accepts_advancing_read_only_samples() -> None:
    verifier = load_verifier()
    report = verifier.evaluate_samples(
        [healthy_status(), healthy_status(11, 22)],
        expected_execution=False,
    )

    assert report["passed"] is True
    assert report["sample_count"] == 2
    assert report["lumos_sequence_advancement"] == 1
    assert report["d435_sequence_advancement"] == 2
    assert report["execution_enabled_samples"] == 0


def test_verifier_rejects_execution_stale_and_nonadvancing_samples() -> None:
    verifier = load_verifier()
    executing = healthy_status()
    executing["activeView"]["executionEnabled"] = True
    stale = healthy_status()
    stale["stale"] = True
    stale["sourceAgeMs"] = 2_001

    report = verifier.evaluate_samples(
        [executing, stale],
        expected_execution=False,
    )

    assert report["passed"] is False
    errors = "\n".join(report["errors"]).lower()
    assert "execution" in errors
    assert "stale" in errors
    assert "did not advance" in errors


def test_verifier_rejects_malformed_or_nonfinite_reports() -> None:
    verifier = load_verifier()
    malformed = healthy_status()
    malformed["activeView"]["reports"][0]["kind"] = "move"
    malformed["activeView"]["reports"][0]["centralFraction"] = float("nan")

    report = verifier.evaluate_samples(
        [malformed, healthy_status(11, 21)],
        expected_execution=False,
    )

    assert report["passed"] is False
    assert "report" in "\n".join(report["errors"]).lower()


def test_verifier_accepts_refinement_without_an_absolute_pose() -> None:
    future_expiry = time.monotonic_ns() + 1_000_000_000
    first = healthy_status()
    first_report = first["activeView"]["reports"][0]
    first_report.update(
        kind="refine_delta",
        targetPoseId=None,
        expiresNs=future_expiry,
        reasons=[],
    )
    second = healthy_status(11, 21)
    second_report = second["activeView"]["reports"][0]
    second_report.update(
        kind="refine_delta",
        targetPoseId=None,
        expiresNs=future_expiry,
        reasons=[],
    )

    report = load_verifier().evaluate_samples([first, second], expected_execution=False)

    assert report["passed"] is True


def test_verifier_rejects_an_expired_proposal() -> None:
    first = healthy_status()
    first["activeView"]["reports"][0].update(
        kind="coarse_pose",
        targetPoseId="table_left",
        expiresNs=1,
        reasons=[],
    )

    report = load_verifier().evaluate_samples(
        [first, healthy_status(11, 21)],
        expected_execution=False,
    )

    assert report["passed"] is False
    assert "expired" in "\n".join(report["errors"]).lower()


def test_launcher_explicitly_locks_active_view_execution_for_dry_run() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "ACTIVE_VIEW_CONFIG" in source
    assert "active_view.yaml" in source
    assert "ACTIVE_VIEW_EXECUTION_ENABLED=0" in source
    assert "ACTIVE_VIEW_EXECUTION_ENABLED=1" not in source
